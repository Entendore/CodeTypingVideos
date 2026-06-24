#include <memory>
#include <variant>
#include <expected>
#include <functional>
#include <string>
#include <string_view>
#include <vector>
#include <array>
#include <atomic>
#include <mutex>
#include <shared_mutex>
#include <condition_variable>
#include <thread>
#include <queue>
#include <concepts>
#include <type_traits>
#include <cassert>
#include <chrono>
#include <format>
#include <print>
#include <algorithm>
#include <ranges>

namespace job_system {

//=============================================================================
// Configuration - Compile-time constants
//=============================================================================

// constinit ensures zero-initialization before any dynamic initialization
constinit size_t g_max_job_name_length = 64;
constinit size_t g_default_queue_capacity = 1024;
constinit size_t g_default_worker_count = 4;
constinit size_t g_max_dependencies = 16;
constinit size_t g_priority_levels = 4;

// consteval forces compile-time evaluation
consteval size_t max_job_name_length() noexcept { return 64; }
consteval size_t default_queue_capacity() noexcept { return 1024; }
consteval size_t default_worker_count() noexcept { return 4; }
consteval size_t priority_level_count() noexcept { return 4; }
consteval size_t max_dependency_count() noexcept { return 16; }

//=============================================================================
// Error Handling
//=============================================================================

enum class JobError : uint8_t {
    InvalidJob,
    AlreadyRunning,
    DependencyFailed,
    DependencyPending,
    Cancelled,
    Timeout,
    QueueFull,
    QueueEmpty,
    SystemNotRunning,
    InvalidPriority,
    TooManyDependencies,
    NullFunction,
    AlreadyCompleted,
    CircularDependency
};

// consteval string conversion for error messages
consteval std::string_view error_to_string(JobError err) noexcept {
    switch (err) {
        case JobError::InvalidJob:          return "Invalid job";
        case JobError::AlreadyRunning:      return "Job already running";
        case JobError::DependencyFailed:    return "Dependency failed";
        case JobError::DependencyPending:   return "Dependency still pending";
        case JobError::Cancelled:           return "Job cancelled";
        case JobError::Timeout:             return "Job timed out";
        case JobError::QueueFull:           return "Job queue is full";
        case JobError::QueueEmpty:          return "Job queue is empty";
        case JobError::SystemNotRunning:    return "Job system not running";
        case JobError::InvalidPriority:     return "Invalid priority level";
        case JobError::TooManyDependencies: return "Too many dependencies";
        case JobError::NullFunction:        return "Job function is null";
        case JobError::AlreadyCompleted:    return "Job already completed";
        case JobError::CircularDependency:  return "Circular dependency detected";
        default:                            return "Unknown error";
    }
}

//=============================================================================
// Job Priority and Status
//=============================================================================

enum class JobPriority : uint8_t {
    Low = 0,
    Normal = 1,
    High = 2,
    Critical = 3
};

// constexpr validation
consteval bool is_valid_priority(JobPriority p) noexcept {
    return static_cast<uint8_t>(p) < priority_level_count();
}

enum class JobStatus : uint8_t {
    Pending = 0,
    Ready = 1,
    Running = 2,
    Completed = 3,
    Failed = 4,
    Cancelled = 5
};

consteval std::string_view status_to_string(JobStatus s) noexcept {
    switch (s) {
        case JobStatus::Pending:   return "Pending";
        case JobStatus::Ready:     return "Ready";
        case JobStatus::Running:   return "Running";
        case JobStatus::Completed: return "Completed";
        case JobStatus::Failed:    return "Failed";
        case JobStatus::Cancelled: return "Cancelled";
        default:                   return "Unknown";
    }
}

//=============================================================================
// Job Result Types using std::variant and std::expected
//=============================================================================

// Variant to hold different return types
using JobValue = std::variant<
    std::monostate,     // No return value (void)
    bool,
    int32_t,
    int64_t,
    uint32_t,
    uint64_t,
    float,
    double,
    std::string,
    std::vector<int32_t>
>;

// Type-safe error handling with expected
using JobResult = std::expected<JobValue, JobError>;

// Helper to create successful results
template<typename T>
constexpr JobResult make_job_success(T&& value) {
    return JobValue{std::forward<T>(value)};
}

constexpr JobResult make_job_success() {
    return JobValue{std::monostate{}};
}

constexpr JobResult make_job_error(JobError err) {
    return std::unexpected(err);
}

//=============================================================================
// Forward Declarations
//=============================================================================

class Job;
class JobSystem;

using JobPtr = std::shared_ptr<Job>;
using WeakJobPtr = std::weak_ptr<Job>;

//=============================================================================
// Job Metadata
//=============================================================================

struct JobMetadata {
    std::string name;
    JobPriority priority{JobPriority::Normal};
    std::chrono::microseconds timeout{0}; // 0 means no timeout
    bool pinned_to_thread{false};
    size_t affinity_thread{0};
};

//=============================================================================
// Job Class
//=============================================================================

class Job : public std::enable_shared_from_this<Job> {
public:
    using ExecuteFunc = std::function<JobResult()>;
    using CompletionCallback = std::function<void(const JobResult&)>;
    using TimePoint = std::chrono::steady_clock::time_point;

private:
    JobMetadata metadata_;
    ExecuteFunc execute_func_;
    std::atomic<JobStatus> status_{JobStatus::Pending};
    JobResult result_{make_job_success()};
    
    // Dependencies
    std::array<WeakJobPtr, max_dependency_count()> dependencies_;
    std::atomic<size_t> dependency_count_{0};
    std::atomic<size_t> completed_dependencies_{0};
    
    // Synchronization
    mutable std::shared_mutex result_mutex_;
    std::condition_variable_any completion_cv_;
    std::mutex callback_mutex_;
    std::vector<CompletionCallback> completion_callbacks_;
    
    // Timing
    TimePoint enqueue_time_;
    TimePoint start_time_;
    TimePoint end_time_;
    std::atomic<bool> has_timeout_{false};
    
    // ID generation
    static std::atomic<uint64_t> next_id_;
    uint64_t id_;

public:
    // Constructors
    constexpr Job() = default;
    
    Job(std::string name, ExecuteFunc func, JobPriority priority = JobPriority::Normal)
        : metadata_{std::move(name), priority, {}, false, 0}
        , execute_func_{std::move(func)}
        , id_{next_id_.fetch_add(1, std::memory_order_relaxed)}
        , enqueue_time_{std::chrono::steady_clock::now()}
    {
        if (metadata_.timeout.count() > 0) {
            has_timeout_ = true;
        }
    }
    
    Job(JobMetadata meta, ExecuteFunc func)
        : metadata_{std::move(meta)}
        , execute_func_{std::move(func)}
        , id_{next_id_.fetch_add(1, std::memory_order_relaxed)}
        , enqueue_time_{std::chrono::steady_clock::now()}
    {
        if (metadata_.timeout.count() > 0) {
            has_timeout_ = true;
        }
    }
    
    // Non-copyable, movable
    Job(const Job&) = delete;
    Job& operator=(const Job&) = delete;
    Job(Job&&) = default;
    Job& operator=(Job&&) = default;
    
    ~Job() = default;

    //=========================================================================
    // Constexpr Accessors
    //=========================================================================
    
    constexpr uint64_t id() const noexcept { return id_; }
    constexpr std::string_view name() const noexcept { return metadata_.name; }
    constexpr JobPriority priority() const noexcept { return metadata_.priority; }
    constexpr bool has_timeout() const noexcept { return has_timeout_.load(); }
    constexpr size_t dependency_count() const noexcept { 
        return dependency_count_.load(std::memory_order_acquire); 
    }
    
    JobStatus status() const noexcept {
        return status_.load(std::memory_order_acquire);
    }
    
    bool is_completed() const noexcept {
        auto s = status();
        return s == JobStatus::Completed || s == JobStatus::Failed || s == JobStatus::Cancelled;
    }
    
    bool is_ready() const noexcept {
        return status_.load(std::memory_order_acquire) == JobStatus::Ready;
    }
    
    bool is_pending() const noexcept {
        return status_.load(std::memory_order_acquire) == JobStatus::Pending;
    }
    
    //=========================================================================
    // Result Access
    //=========================================================================
    
    std::expected<JobValue, JobError> get_result() const {
        std::shared_lock lock{result_mutex_};
        return result_;
    }
    
    template<typename T>
    std::expected<T, JobError> get_result_as() const {
        std::shared_lock lock{result_mutex_};
        if (!result_.has_value()) {
            return std::unexpected(result_.error());
        }
        const auto& val = result_.value();
        if (auto* ptr = std::get_if<T>(&val)) {
            return *ptr;
        }
        return std::unexpected(JobError::InvalidJob);
    }
    
    //=========================================================================
    // Dependency Management
    //=========================================================================
    
    std::expected<void, JobError> add_dependency(WeakJobPtr dependency) {
        if (auto dep = dependency.lock()) {
            if (dep.get() == this) {
                return std::unexpected(JobError::CircularDependency);
            }
        }
        
        auto count = dependency_count_.load(std::memory_order_acquire);
        if (count >= max_dependency_count()) {
            return std::unexpected(JobError::TooManyDependencies);
        }
        
        // Check if already added
        for (size_t i = 0; i < count; ++i) {
            if (auto dep = dependencies_[i].lock()) {
                if (dep.get() == dependency.lock().get()) {
                    return {}; // Already exists, not an error
                }
            }
        }
        
        dependencies_[count] = std::move(dependency);
        dependency_count_.fetch_add(1, std::memory_order_release);
        return {};
    }
    
    void notify_dependency_completed() {
        auto completed = completed_dependencies_.fetch_add(1, std::memory_order_acq_rel) + 1;
        auto total = dependency_count_.load(std::memory_order_acquire);
        
        if (completed >= total && status() == JobStatus::Pending) {
            status_.store(JobStatus::Ready, std::memory_order_release);
        }
    }
    
    void check_dependencies_failed() {
        for (size_t i = 0; i < dependency_count_.load(std::memory_order_acquire); ++i) {
            if (auto dep = dependencies_[i].lock()) {
                if (dep->status() == JobStatus::Failed) {
                    status_.store(JobStatus::Cancelled, std::memory_order_release);
                    result_ = make_job_error(JobError::DependencyFailed);
                    notify_completion();
                    return;
                }
            }
        }
    }
    
    //=========================================================================
    // Execution
    //=========================================================================
    
    std::expected<void, JobError> execute() {
        JobStatus expected = JobStatus::Ready;
        if (!status_.compare_exchange_strong(expected, JobStatus::Running,
                                             std::memory_order_acq_rel)) {
            return std::unexpected(JobError::AlreadyRunning);
        }
        
        if (!execute_func_) {
            status_.store(JobStatus::Failed, std::memory_order_release);
            result_ = make_job_error(JobError::NullFunction);
            notify_completion();
            return std::unexpected(JobError::NullFunction);
        }
        
        start_time_ = std::chrono::steady_clock::now();
        
        try {
            result_ = execute_func_();
            if (result_.has_value()) {
                status_.store(JobStatus::Completed, std::memory_order_release);
            } else {
                status_.store(JobStatus::Failed, std::memory_order_release);
            }
        } catch (...) {
            status_.store(JobStatus::Failed, std::memory_order_release);
            result_ = make_job_error(JobError::InvalidJob);
        }
        
        end_time_ = std::chrono::steady_clock::now();
        notify_completion();
        
        return {};
    }
    
    std::expected<void, JobError> cancel() {
        auto current = status_.load(std::memory_order_acquire);
        if (current == JobStatus::Running) {
            return std::unexpected(JobError::AlreadyRunning);
        }
        if (current == JobStatus::Completed || current == JobStatus::Failed) {
            return std::unexpected(JobError::AlreadyCompleted);
        }
        
        status_.store(JobStatus::Cancelled, std::memory_order_release);
        result_ = make_job_error(JobError::Cancelled);
        notify_completion();
        return {};
    }
    
    //=========================================================================
    // Callbacks
    //=========================================================================
    
    void add_completion_callback(CompletionCallback callback) {
        std::lock_guard lock{callback_mutex_};
        completion_callbacks_.push_back(std::move(callback));
    }
    
    void wait_for_completion(std::chrono::milliseconds timeout_ms = std::chrono::milliseconds::max()) const {
        std::unique_lock lock{result_mutex_};
        if (is_completed()) {
            return;
        }
        completion_cv_.wait_for(lock, timeout_ms, [this] { return is_completed(); });
    }
    
    //=========================================================================
    // Timing
    //=========================================================================
    
    constexpr TimePoint enqueue_time() const noexcept { return enqueue_time_; }
    constexpr TimePoint start_time() const noexcept { return start_time_; }
    constexpr TimePoint end_time() const noexcept { return end_time_; }
    
    std::chrono::microseconds execution_duration() const noexcept {
        if (start_time_ == TimePoint{} || end_time_ == TimePoint{}) {
            return std::chrono::microseconds{0};
        }
        return std::chrono::duration_cast<std::chrono::microseconds>(end_time_ - start_time_);
    }
    
    std::chrono::microseconds wait_duration() const noexcept {
        if (enqueue_time_ == TimePoint{} || start_time_ == TimePoint{}) {
            return std::chrono::microseconds{0};
        }
        return std::chrono::duration_cast<std::chrono::microseconds>(start_time_ - enqueue_time_);
    }
    
    //=========================================================================
    // Debug
    //=========================================================================
    
    void print_debug_info() const {
        std::println("Job[{}]: '{}' | Status: {} | Priority: {} | Deps: {}/{} | Duration: {}us",
            id_, metadata_.name, 
            status_to_string(status()),
            static_cast<int>(metadata_.priority),
            completed_dependencies_.load(), dependency_count_.load(),
            execution_duration().count());
    }

private:
    void notify_completion() {
        std::vector<CompletionCallback> callbacks;
        {
            std::lock_guard lock{callback_mutex_};
            callbacks = std::move(completion_callbacks_);
            completion_callbacks_.clear();
        }
        
        for (auto& cb : callbacks) {
            try {
                cb(result_);
            } catch (...) {
                // Swallow callback exceptions
            }
        }
        
        completion_cv_.notify_all();
    }
};

// Static member initialization
std::atomic<uint64_t> Job::next_id_{0};

//=============================================================================
// Thread-Safe Job Queue using Smart Pointers
//=============================================================================

template<size_t Capacity = default_queue_capacity()>
class JobQueue {
private:
    // Ring buffer with smart pointers
    std::array<JobPtr, Capacity> buffer_{};
    std::atomic<size_t> head_{0};
    std::atomic<size_t> tail_{0};
    std::atomic<size_t> size_{0};
    
    mutable std::mutex mutex_;
    std::condition_variable not_empty_cv_;
    std::condition_variable not_full_cv_;
    std::atomic<bool> shutdown_{false};

public:
    static_assert(Capacity > 0, "Queue capacity must be positive");
    
    constexpr JobQueue() = default;
    ~JobQueue() { shutdown(); }
    
    JobQueue(const JobQueue&) = delete;
    JobQueue& operator=(const JobQueue&) = delete;
    JobQueue(JobQueue&&) = delete;
    JobQueue& operator=(JobQueue&&) = delete;
    
    // consteval for compile-time capacity check
    consteval static size_t capacity() noexcept { return Capacity; }
    
    constexpr size_t size() const noexcept { return size_.load(std::memory_order_acquire); }
    constexpr bool empty() const noexcept { return size_.load(std::memory_order_acquire) == 0; }
    constexpr bool full() const noexcept { return size_.load(std::memory_order_acquire) >= Capacity; }
    
    std::expected<void, JobError> push(JobPtr job) {
        if (!job) {
            return std::unexpected(JobError::InvalidJob);
        }
        
        std::unique_lock lock{mutex_};
        
        if (shutdown_.load()) {
            return std::unexpected(JobError::SystemNotRunning);
        }
        
        not_full_cv_.wait(lock, [this] {
            return !full() || shutdown_.load();
        });
        
        if (shutdown_.load()) {
            return std::unexpected(JobError::SystemNotRunning);
        }
        
        buffer_[tail_ % Capacity] = std::move(job);
        tail_.store(tail_.load(std::memory_order_relaxed) + 1, std::memory_order_release);
        size_.fetch_add(1, std::memory_order_release);
        
        not_empty_cv_.notify_one();
        return {};
    }
    
    // Priority-aware push: inserts based on job priority
    std::expected<void, JobError> push_priority(JobPtr job) {
        if (!job) {
            return std::unexpected(JobError::InvalidJob);
        }
        
        std::unique_lock lock{mutex_};
        
        if (shutdown_.load()) {
            return std::unexpected(JobError::SystemNotRunning);
        }
        
        not_full_cv_.wait(lock, [this] {
            return !full() || shutdown_.load();
        });
        
        if (shutdown_.load()) {
            return std::unexpected(JobError::SystemNotRunning);
        }
        
        // Find insertion point based on priority (higher priority = earlier)
        size_t insert_pos = tail_.load(std::memory_order_relaxed);
        size_t current = head_.load(std::memory_order_relaxed);
        size_t count = size_.load(std::memory_order_relaxed);
        
        for (size_t i = 0; i < count; ++i) {
            size_t idx = (current + i) % Capacity;
            if (buffer_[idx] && buffer_[idx]->priority() < job->priority()) {
                insert_pos = idx;
                break;
            }
        }
        
        // Shift elements to make room
        if (insert_pos < tail_.load(std::memory_order_relaxed)) {
            for (size_t i = count; i > 0; --i) {
                size_t src = (current + i - 1) % Capacity;
                size_t dst = (current + i) % Capacity;
                buffer_[dst] = std::move(buffer_[src]);
            }
        }
        
        buffer_[insert_pos % Capacity] = std::move(job);
        tail_.store(tail_.load(std::memory_order_relaxed) + 1, std::memory_order_release);
        size_.fetch_add(1, std::memory_order_release);
        
        not_empty_cv_.notify_one();
        return {};
    }
    
    std::expected<JobPtr, JobError> pop() {
        std::unique_lock lock{mutex_};
        
        not_empty_cv_.wait(lock, [this] {
            return !empty() || shutdown_.load();
        });
        
        if (empty()) {
            return std::unexpected(JobError::QueueEmpty);
        }
        
        auto job = std::move(buffer_[head_ % Capacity]);
        buffer_[head_ % Capacity].reset(); // Clear the smart pointer
        head_.store(head_.load(std::memory_order_relaxed) + 1, std::memory_order_release);
        size_.fetch_sub(1, std::memory_order_release);
        
        not_full_cv_.notify_one();
        return job;
    }
    
    // Try pop without blocking
    std::expected<JobPtr, JobError> try_pop() {
        std::unique_lock lock{mutex_, std::try_to_lock};
        if (!lock || empty()) {
            return std::unexpected(JobError::QueueEmpty);
        }
        
        auto job = std::move(buffer_[head_ % Capacity]);
        buffer_[head_ % Capacity].reset();
        head_.store(head_.load(std::memory_order_relaxed) + 1, std::memory_order_release);
        size_.fetch_sub(1, std::memory_order_release);
        
        not_full_cv_.notify_one();
        return job;
    }
    
    void shutdown() {
        shutdown_.store(true);
        not_empty_cv_.notify_all();
        not_full_cv_.notify_all();
    }
    
    void clear() {
        std::unique_lock lock{mutex_};
        for (size_t i = 0; i < size_.load(); ++i) {
            buffer_[(head_.load() + i) % Capacity].reset();
        }
        head_.store(0, std::memory_order_release);
        tail_.store(0, std::memory_order_release);
        size_.store(0, std::memory_order_release);
        not_full_cv_.notify_all();
    }
};

//=============================================================================
// Per-Priority Job Queue Container
//=============================================================================

class PriorityJobQueue {
private:
    std::array<std::unique_ptr<JobQueue<>>, priority_level_count()> queues_;
    
public:
    PriorityJobQueue() {
        for (size_t i = 0; i < priority_level_count(); ++i) {
            queues_[i] = std::make_unique<JobQueue<>>();
        }
    }
    
    ~PriorityJobQueue() = default;
    
    std::expected<void, JobError> push(JobPtr job) {
        auto priority_idx = static_cast<size_t>(job->priority());
        if (priority_idx >= priority_level_count()) {
            return std::unexpected(JobError::InvalidPriority);
        }
        return queues_[priority_idx]->push(std::move(job));
    }
    
    std::expected<JobPtr, JobError> pop_highest_priority() {
        // Try to pop from highest priority first
        for (size_t i = priority_level_count(); i > 0; --i) {
            if (auto result = queues_[i - 1]->try_pop(); result.has_value()) {
                return result;
            }
        }
        return std::unexpected(JobError::QueueEmpty);
    }
    
    std::expected<JobPtr, JobError> wait_pop() {
        while (true) {
            // Check all queues from highest to lowest priority
            for (size_t i = priority_level_count(); i > 0; --i) {
                if (auto result = queues_[i - 1]->try_pop(); result.has_value()) {
                    return result;
                }
            }
            // Brief sleep to avoid busy waiting
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
    }
    
    void shutdown() {
        for (auto& q : queues_) {
            q->shutdown();
        }
    }
    
    void clear() {
        for (auto& q : queues_) {
            q->clear();
        }
    }
    
    constexpr size_t total_size() const noexcept {
        size_t total = 0;
        for (const auto& q : queues_) {
            total += q->size();
        }
        return total;
    }
    
    constexpr bool empty() const noexcept {
        return std::ranges::all_of(queues_, [](const auto& q) { return q->empty(); });
    }
};

//=============================================================================
// Worker Thread
//=============================================================================

class WorkerThread {
public:
    enum class State : uint8_t {
        Idle,
        Running,
        Waiting,
        Stopped
    };

private:
    std::jthread thread_;
    std::atomic<State> state_{State::Idle};
    JobSystem* system_{nullptr};
    size_t worker_id_{0};
    JobPtr current_job_{nullptr};
    std::atomic<uint64_t> jobs_executed_{0};
    std::atomic<uint64_t> jobs_failed_{0};

public:
    WorkerThread() = default;
    
    WorkerThread(size_t id, JobSystem* system);
    ~WorkerThread() { stop(); }
    
    WorkerThread(const WorkerThread&) = delete;
    WorkerThread& operator=(const WorkerThread&) = delete;
    WorkerThread(WorkerThread&&) noexcept = default;
    WorkerThread& operator=(WorkerThread&&) noexcept = default;
    
    void start();
    void stop();
    
    constexpr State state() const noexcept { return state_.load(std::memory_order_acquire); }
    constexpr size_t worker_id() const noexcept { return worker_id_; }
    constexpr uint64_t jobs_executed() const noexcept { return jobs_executed_.load(std::memory_order_relaxed); }
    constexpr uint64_t jobs_failed() const noexcept { return jobs_failed_.load(std::memory_order_relaxed); }
    constexpr bool is_busy() const noexcept { return state_.load() == State::Running; }
    
    void worker_loop(std::stop_token token);

private:
    void process_job(JobPtr job);
};

//=============================================================================
// Job System Statistics
//=============================================================================

struct JobSystemStats {
    uint64_t total_jobs_submitted{0};
    uint64_t total_jobs_completed{0};
    uint64_t total_jobs_failed{0};
    uint64_t total_jobs_cancelled{0};
    uint64_t total_jobs_in_flight{0};
    uint64_t total_jobs_waiting{0};
    double average_wait_time_us{0.0};
    double average_execution_time_us{0.0};
    size_t queue_size{0};
    size_t worker_count{0};
};

//=============================================================================
// Main Job System
//=============================================================================

class JobSystem {
public:
    // Singleton-like access with explicit lifetime management
    static JobSystem& instance() {
        static JobSystem system{default_worker_count()};
        return system;
    }

private:
    std::vector<std::unique_ptr<WorkerThread>> workers_;
    PriorityJobQueue job_queue_;
    
    // Job tracking
    std::mutex pending_jobs_mutex_;
    std::vector<WeakJobPtr> pending_jobs_;
    
    std::atomic<bool> running_{false};
    std::atomic<uint64_t> stats_submitted_{0};
    std::atomic<uint64_t> stats_completed_{0};
    std::atomic<uint64_t> stats_failed_{0};
    std::atomic<uint64_t> stats_cancelled_{0};
    std::atomic<double> total_wait_time_us_{0.0};
    std::atomic<double> total_exec_time_us_{0.0};
    
    size_t worker_count_;

public:
    explicit JobSystem(size_t worker_count = default_worker_count())
        : worker_count_{worker_count}
    {
        workers_.reserve(worker_count);
        for (size_t i = 0; i < worker_count; ++i) {
            workers_.push_back(std::make_unique<WorkerThread>(i, this));
        }
    }
    
    ~JobSystem() {
        shutdown();
    }
    
    JobSystem(const JobSystem&) = delete;
    JobSystem& operator=(const JobSystem&) = delete;
    
    //=========================================================================
    // Lifecycle
    //=========================================================================
    
    std::expected<void, JobError> start() {
        bool expected = false;
        if (!running_.compare_exchange_strong(expected, true, 
                                             std::memory_order_acq_rel)) {
            return std::unexpected(JobError::AlreadyRunning);
        }
        
        for (auto& worker : workers_) {
            worker->start();
        }
        
        return {};
    }
    
    void shutdown() {
        if (!running_.exchange(false, std::memory_order_acq_rel)) {
            return;
        }
        
        job_queue_.shutdown();
        
        for (auto& worker : workers_) {
            worker->stop();
        }
        
        // Clean up pending jobs
        std::lock_guard lock{pending_jobs_mutex_};
        for (auto& weak_job : pending_jobs_) {
            if (auto job = weak_job.lock()) {
                job->cancel();
            }
        }
        pending_jobs_.clear();
    }
    
    constexpr bool is_running() const noexcept { 
        return running_.load(std::memory_order_acquire); 
    }
    
    //=========================================================================
    // Job Submission
    //=========================================================================
    
    std::expected<JobPtr, JobError> submit(std::string name, Job::ExecuteFunc func, 
                                           JobPriority priority = JobPriority::Normal) {
        if (!is_running()) {
            return std::unexpected(JobError::SystemNotRunning);
        }
        if (!func) {
            return std::unexpected(JobError::NullFunction);
        }
        
        auto job = std::make_shared<Job>(std::move(name), std::move(func), priority);
        return submit_job(std::move(job));
    }
    
    std::expected<JobPtr, JobError> submit(JobMetadata meta, Job::ExecuteFunc func) {
        if (!is_running()) {
            return std::unexpected(JobError::SystemNotRunning);
        }
        if (!func) {
            return std::unexpected(JobError::NullFunction);
        }
        
        auto job = std::make_shared<Job>(std::move(meta), std::move(func));
        return submit_job(std::move(job));
    }
    
    std::expected<JobPtr, JobError> submit_with_dependencies(
        std::string name, 
        Job::ExecuteFunc func,
        std::vector<WeakJobPtr> dependencies,
        JobPriority priority = JobPriority::Normal) 
    {
        if (!is_running()) {
            return std::unexpected(JobError::SystemNotRunning);
        }
        if (!func) {
            return std::unexpected(JobError::NullFunction);
        }
        
        auto job = std::make_shared<Job>(std::move(name), std::move(func), priority);
        
        for (auto& dep : dependencies) {
            if (auto result = job->add_dependency(std::move(dep)); !result.has_value()) {
                return std::unexpected(result.error());
            }
        }
        
        return submit_job(std::move(job));
    }
    
    //=========================================================================
    // Job Execution
    //=========================================================================
    
    std::expected<JobPtr, JobError> try_get_job() {
        return job_queue_.pop_highest_priority();
    }
    
    std::expected<JobPtr, JobError> wait_for_job() {
        return job_queue_.wait_pop();
    }
    
    void notify_job_completed(JobPtr job) {
        if (job->status() == JobStatus::Completed) {
            stats_completed_.fetch_add(1, std::memory_order_relaxed);
            total_wait_time_us_.store(
                total_wait_time_us_.load(std::memory_order_relaxed) + 
                job->wait_duration().count(), 
                std::memory_order_relaxed);
            total_exec_time_us_.store(
                total_exec_time_us_.load(std::memory_order_relaxed) + 
                job->execution_duration().count(), 
                std::memory_order_relaxed);
        } else if (job->status() == JobStatus::Failed) {
            stats_failed_.fetch_add(1, std::memory_order_relaxed);
        }
        
        // Notify dependent jobs
        std::lock_guard lock{pending_jobs_mutex_};
        for (auto& weak_job : pending_jobs_) {
            if (auto dep_job = weak_job.lock()) {
                if (dep_job.get() != job.get()) {
                    dep_job->notify_dependency_completed();
                    dep_job->check_dependencies_failed();
                }
            }
        }
    }
    
    //=========================================================================
    // Statistics
    //=========================================================================
    
    JobSystemStats get_stats() const {
        JobSystemStats stats{};
        stats.total_jobs_submitted = stats_submitted_.load(std::memory_order_relaxed);
        stats.total_jobs_completed = stats_completed_.load(std::memory_order_relaxed);
        stats.total_jobs_failed = stats_failed_.load(std::memory_order_relaxed);
        stats.total_jobs_cancelled = stats_cancelled_.load(std::memory_order_relaxed);
        stats.queue_size = job_queue_.total_size();
        stats.worker_count = worker_count_;
        
        auto completed = stats_completed_.load();
        if (completed > 0) {
            stats.average_wait_time_us = total_wait_time_us_.load() / completed;
            stats.average_execution_time_us = total_exec_time_us_.load() / completed;
        }
        
        return stats;
    }
    
    void print_stats() const {
        auto stats = get_stats();
        std::println("=== Job System Statistics ===");
        std::println("  Workers: {}", stats.worker_count);
        std::println("  Queue Size: {}", stats.queue_size);
        std::println("  Submitted: {}", stats.total_jobs_submitted);
        std::println("  Completed: {}", stats.total_jobs_completed);
        std::println("  Failed: {}", stats.total_jobs_failed);
        std::println("  Cancelled: {}", stats.total_jobs_cancelled);
        std::println("  Avg Wait Time: {:.2f} us", stats.average_wait_time_us);
        std::println("  Avg Exec Time: {:.2f} us", stats.average_execution_time_us);
        std::println("==============================");
    }
    
    //=========================================================================
    // Utility
    //=========================================================================
    
    void wait_for_all_pending() {
        while (job_queue_.total_size() > 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        
        // Wait for all workers to finish current jobs
        for (const auto& worker : workers_) {
            while (worker->is_busy()) {
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
        }
    }

private:
    std::expected<JobPtr, JobError> submit_job(JobPtr job) {
        // Check if job has no dependencies - make it ready immediately
        if (job->dependency_count() == 0) {
            job->status_.store(JobStatus::Ready, std::memory_order_release);
        }
        
        // Track pending job
        {
            std::lock_guard lock{pending_jobs_mutex_};
            pending_jobs_.push_back(job);
            
            // Clean up completed/failed jobs
            std::erase_if(pending_jobs_, [](const WeakJobPtr& weak) {
                return weak.expired() || weak.lock()->is_completed();
            });
        }
        
        // Add completion callback for cleanup
        job->add_completion_callback([this](const JobResult&) {
            stats_cancelled_.fetch_add(0, std::memory_order_relaxed); // Just for notification
        });
        
        auto result = job_queue_.push(std::move(job));
        if (result.has_value()) {
            stats_submitted_.fetch_add(1, std::memory_order_relaxed);
        }
        
        // Return a copy of the job pointer for tracking
        if (auto queued_job = job_queue_.try_pop(); queued_job.has_value()) {
            job_queue_.push(std::move(*queued_job));
            return queued_job;
        }
        
        // The job was successfully queued, return it via pending list
        std::lock_guard lock{pending_jobs_mutex_};
        if (!pending_jobs_.empty()) {
            return pending_jobs_.back().lock();
        }
        
        return std::unexpected(JobError::QueueFull);
    }
};

//=============================================================================
// Worker Thread Implementation
//=============================================================================

WorkerThread::WorkerThread(size_t id, JobSystem* system)
    : worker_id_{id}, system_{system} {}

void WorkerThread::start() {
    state_.store(State::Idle, std::memory_order_release);
    thread_ = std::jthread{&WorkerThread::worker_loop, this, std::placeholders::_1};
}

void WorkerThread::stop() {
    if (state_.load() != State::Stopped) {
        state_.store(State::Stopped, std::memory_order_release);
        if (thread_.joinable()) {
            thread_.request_stop();
            thread_.join();
        }
    }
}

void WorkerThread::worker_loop(std::stop_token token) {
    state_.store(State::Waiting, std::memory_order_release);
    
    while (!token.stop_requested()) {
        state_.store(State::Waiting, std::memory_order_release);
        
        if (auto result = system_->try_get_job(); result.has_value()) {
            process_job(std::move(*result));
        } else {
            // Brief sleep when no jobs available
            std::this_thread::sleep_for(std::chrono::microseconds(50));
        }
    }
    
    state_.store(State::Stopped, std::memory_order_release);
}

void WorkerThread::process_job(JobPtr job) {
    if (!job) return;
    
    current_job_ = job;
    state_.store(State::Running, std::memory_order_release);
    
    // Execute the job
    auto result = job->execute();
    
    if (!result.has_value()) {
        jobs_failed_.fetch_add(1, std::memory_order_relaxed);
    }
    jobs_executed_.fetch_add(1, std::memory_order_relaxed);
    
    // Notify system
    system_->notify_job_completed(job);
    
    current_job_.reset();
    state_.store(State::Waiting, std::memory_order_release);
}

//=============================================================================
// Job Builder - Fluent API
//=============================================================================

class JobBuilder {
private:
    std::string name_;
    Job::ExecuteFunc func_;
    JobPriority priority_{JobPriority::Normal};
    std::vector<WeakJobPtr> dependencies_;
    std::chrono::microseconds timeout_{0};
    bool pinned_{false};
    size_t affinity_{0};

public:
    explicit JobBuilder(std::string name) : name_{std::move(name)} {}
    
    JobBuilder& with_func(Job::ExecuteFunc func) {
        func_ = std::move(func);
        return *this;
    }
    
    JobBuilder& with_priority(JobPriority priority) {
        priority_ = priority;
        return *this;
    }
    
    JobBuilder& with_dependency(WeakJobPtr dep) {
        dependencies_.push_back(std::move(dep));
        return *this;
    }
    
    JobBuilder& with_dependencies(std::vector<WeakJobPtr> deps) {
        dependencies_ = std::move(deps);
        return *this;
    }
    
    JobBuilder& with_timeout(std::chrono::microseconds timeout) {
        timeout_ = timeout;
        return *this;
    }
    
    JobBuilder& pinned_to_thread(size_t thread_id) {
        pinned_ = true;
        affinity_ = thread_id;
        return *this;
    }
    
    std::expected<JobPtr, JobError> submit_to(JobSystem& system) {
        if (!func_) {
            return std::unexpected(JobError::NullFunction);
        }
        
        JobMetadata meta{
            std::move(name_),
            priority_,
            timeout_,
            pinned_,
            affinity_
        };
        
        if (dependencies_.empty()) {
            return system.submit(std::move(meta), std::move(func_));
        }
        
        return system.submit_with_dependencies(
            meta.name, 
            std::move(func_), 
            std::move(dependencies_), 
            meta.priority
        );
    }
};

//=============================================================================
// Utility Functions
//=============================================================================

// Create a job that returns a value
template<typename T>
constexpr Job::ExecuteFunc make_job_func(std::invocable<T> auto fn) {
    return [f = std::move(fn)]() -> JobResult {
        try {
            if constexpr (std::is_void_v<T>) {
                f();
                return make_job_success();
            } else {
                return make_job_success(f());
            }
        } catch (...) {
            return make_job_error(JobError::InvalidJob);
        }
    };
}

// Simplified job creation
template<typename F>
requires std::invocable<F>
Job::ExecuteFunc make_simple_job(F fn) {
    using ReturnType = std::invoke_result_t<F>;
    return [f = std::move(fn)]() -> JobResult {
        try {
            if constexpr (std::is_void_v<ReturnType>) {
                f();
                return make_job_success();
            } else {
                return make_job_success(f());
            }
        } catch (...) {
            return make_job_error(JobError::InvalidJob);
        }
    };
}

// Create a batch of dependent jobs
std::expected<std::vector<JobPtr>, JobError> create_job_chain(
    JobSystem& system,
    std::vector<std::pair<std::string, Job::ExecuteFunc>> tasks,
    JobPriority priority = JobPriority::Normal)
{
    std::vector<JobPtr> jobs;
    jobs.reserve(tasks.size());
    
    for (size_t i = 0; i < tasks.size(); ++i) {
        auto& [name, func] = tasks[i];
        
        std::vector<WeakJobPtr> deps;
        if (i > 0 && !jobs.empty()) {
            deps.push_back(jobs.back());
        }
        
        auto result = system.submit_with_dependencies(
            std::move(name), 
            std::move(func), 
            std::move(deps), 
            priority
        );
        
        if (!result.has_value()) {
            return std::unexpected(result.error());
        }
        
        jobs.push_back(std::move(*result));
    }
    
    return jobs;
}

// Create parallel jobs that can be joined
std::expected<std::vector<JobPtr>, JobError> create_parallel_jobs(
    JobSystem& system,
    std::vector<std::pair<std::string, Job::ExecuteFunc>> tasks,
    JobPriority priority = JobPriority::Normal)
{
    std::vector<JobPtr> jobs;
    jobs.reserve(tasks.size());
    
    for (auto& [name, func] : tasks) {
        auto result = system.submit(std::move(name), std::move(func), priority);
        
        if (!result.has_value()) {
            return std::unexpected(result.error());
        }
        
        jobs.push_back(std::move(*result));
    }
    
    return jobs;
}

// Wait for all jobs in a vector to complete
void wait_for_all(const std::vector<JobPtr>& jobs, 
                  std::chrono::milliseconds timeout = std::chrono::milliseconds::max()) {
    for (const auto& job : jobs) {
        if (job) {
            job->wait_for_completion(timeout);
        }
    }
}

// Check if all jobs completed successfully
bool all_completed_successfully(const std::vector<JobPtr>& jobs) {
    return std::ranges::all_of(jobs, [](const JobPtr& job) {
        return job && job->status() == JobStatus::Completed;
    });
}

} // namespace job_system

//=============================================================================
// Example Usage
//=============================================================================

int main() {
    using namespace job_system;
    
    std::println("=== C++23 Job System Demo ===\n");
    
    // Create and start job system
    JobSystem job_system{4};
    
    auto start_result = job_system.start();
    if (!start_result) {
        std::println("Failed to start job system: {}", error_to_string(start_result.error()));
        return 1;
    }
    
    std::println("Job system started with 4 workers\n");
    
    //-------------------------------------------------------------------------
    // Example 1: Simple jobs
    //-------------------------------------------------------------------------
    std::println("--- Example 1: Simple Jobs ---");
    
    auto job1 = job_system.submit("Compute Sum", []() -> JobResult {
        int64_t sum = 0;
        for (int i = 1; i <= 100; ++i) sum += i;
        return make_job_success(sum);
    }, JobPriority::Normal);
    
    auto job2 = job_system.submit("Check Prime", []() -> JobResult {
        return make_job_success(true);
    }, JobPriority::High);
    
    auto job3 = job_system.submit("Generate String", []() -> JobResult {
        return make_job_success(std::string("Hello from Job System!"));
    }, JobPriority::Low);
    
    if (job1) (*job1)->wait_for_completion();
    if (job2) (*job2)->wait_for_completion();
    if (job3) (*job3)->wait_for_completion();
    
    if (job1 && (*job1)->get_result().has_value()) {
        auto val = (*job1)->get_result_as<int64_t>();
        if (val) std::println("  Sum: {}", *val);
    }
    
    if (job3 && (*job3)->get_result().has_value()) {
        auto val = (*job3)->get_result_as<std::string>();
        if (val) std::println("  String: {}", *val);
    }
    
    //-------------------------------------------------------------------------
    // Example 2: Job with callback
    //-------------------------------------------------------------------------
    std::println("\n--- Example 2: Job with Callback ---");
    
    std::atomic<bool> callback_called{false};
    
    auto callback_job = job_system.submit("Callback Job", [&callback_called]() -> JobResult {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        return make_job_success(42);
    }, JobPriority::High);
    
    if (callback_job) {
        (*callback_job)->add_completion_callback([&callback_called](const JobResult& result) {
            callback_called.store(true);
            if (result.has_value()) {
                if (auto* val = std::get_if<int32_t>(&result.value())) {
                    std::println("  Callback received value: {}", *val);
                }
            }
        });
        (*callback_job)->wait_for_completion();
    }
    
    std::println("  Callback called: {}", callback_called.load());
    
    //-------------------------------------------------------------------------
    // Example 3: Job Builder (Fluent API)
    //-------------------------------------------------------------------------
    std::println("\n--- Example 3: Job Builder ---");
    
    auto built_job = JobBuilder{"Builder Job"}
        .with_func([]() -> JobResult {
            return make_job_success(std::vector<int32_t>{1, 2, 3, 4, 5});
        })
        .with_priority(JobPriority::Critical)
        .with_timeout(std::chrono::seconds(5))
        .submit_to(job_system);
    
    if (built_job) {
        (*built_job)->wait_for_completion();
        auto result = (*built_job)->get_result_as<std::vector<int32_t>>();
        if (result) {
            std::print("  Vector values: ");
            for (auto v : *result) std::print("{} ", v);
            std::println();
        }
    }
    
    //-------------------------------------------------------------------------
    // Example 4: Dependent jobs (chain)
    //-------------------------------------------------------------------------
    std::println("\n--- Example 4: Job Chain ---");
    
    auto chain = create_job_chain(job_system, {
        {"Step 1: Initialize", []() -> JobResult {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            return make_job_success(100);
        }},
        {"Step 2: Process", []() -> JobResult {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            return make_job_success(200);
        }},
        {"Step 3: Finalize", []() -> JobResult {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            return make_job_success(300);
        }}
    }, JobPriority::Normal);
    
    if (chain) {
        wait_for_all(*chain);
        for (const auto& job : *chain) {
            job->print_debug_info();
        }
    }
    
    //-------------------------------------------------------------------------
    // Example 5: Parallel jobs
    //-------------------------------------------------------------------------
    std::println("\n--- Example 5: Parallel Jobs ---");
    
    auto parallel = create_parallel_jobs(job_system, {
        {"Parallel 1", []() -> JobResult { 
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
            return make_job_success(1); 
        }},
        {"Parallel 2", []() -> JobResult { 
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
            return make_job_success(2); 
        }},
        {"Parallel 3", []() -> JobResult { 
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
            return make_job_success(3); 
        }},
        {"Parallel 4", []() -> JobResult { 
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
            return make_job_success(4); 
        }}
    }, JobPriority::High);
    
    if (parallel) {
        wait_for_all(*parallel);
        std::println("  All parallel jobs completed: {}", all_completed_successfully(*parallel));
    }
    
    //-------------------------------------------------------------------------
    // Example 6: Job with dependencies
    //-------------------------------------------------------------------------
    std::println("\n--- Example 6: Manual Dependencies ---");
    
    auto dep1 = job_system.submit("Dependency 1", []() -> JobResult {
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        return make_job_success("Data from dep1");
    });
    
    auto dep2 = job_system.submit("Dependency 2", []() -> JobResult {
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        return make_job_success("Data from dep2");
    });
    
    std::vector<WeakJobPtr> deps;
    if (dep1) deps.push_back(*dep1);
    if (dep2) deps.push_back(*dep2);
    
    auto dependent = job_system.submit_with_dependencies(
        "Dependent Job",
        []() -> JobResult {
            return make_job_success(std::string("Combined result"));
        },
        deps,
        JobPriority::High
    );
    
    if (dependent) {
        (*dependent)->wait_for_completion();
        (*dependent)->print_debug_info();
    }
    
    //-------------------------------------------------------------------------
    // Example 7: Error handling
    //-------------------------------------------------------------------------
    std::println("\n--- Example 7: Error Handling ---");
    
    auto failing_job = job_system.submit("Failing Job", []() -> JobResult {
        return make_job_error(JobError::InvalidJob);
    });
    
    if (failing_job) {
        (*failing_job)->wait_for_completion();
        auto result = (*failing_job)->get_result();
        if (!result.has_value()) {
            std::println("  Job failed as expected: {}", error_to_string(result.error()));
        }
        (*failing_job)->print_debug_info();
    }
    
    // Test invalid submission
    auto invalid = job_system.submit("Null Func", nullptr);
    if (!invalid) {
        std::println("  Null function rejected: {}", error_to_string(invalid.error()));
    }
    
    //-------------------------------------------------------------------------
    // Wait and print stats
    //-------------------------------------------------------------------------
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    job_system.wait_for_all_pending();
    
    std::println("\n--- Final Statistics ---");
    job_system.print_stats();
    
    // Shutdown
    job_system.shutdown();
    std::println("\nJob system shutdown complete.");
    
    return 0;
}