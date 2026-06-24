// vulkan_spinning_cube.cpp
// Compile: g++ -std=c++23 -O2 vulkan_spinning_cube.cpp -lvulkan -lglfw -o vk_cube

#define VULKAN_HPP_NO_EXCEPTIONS
#define VULKAN_HPP_DISPATCH_LOADER_DYNAMIC 1
#define VULKAN_HPP_STORAGE_SHARED
#include <vulkan/vulkan.hpp>

#include <GLFW/glfw3.h>

#include <memory>
#include <expected>
#include <variant>
#include <vector>
#include <array>
#include <string_view>
#include <print>
#include <source_location>
#include <span>
#include <ranges>
#include <algorithm>
#include <chrono>
#include <concepts>
#include <functional>

//=============================================================================
// C++23 Feature Demonstrations
//=============================================================================

// constinit - guaranteed compile-time initialization
constinit const double PI = 3.14159265358979323846;

// consteval - MUST be evaluated at compile time
consteval float deg_to_rad(float degrees) noexcept {
    return static_cast<float>(degrees * PI / 180.0);
}

// constexpr - CAN be evaluated at compile time
constexpr float rad_to_deg(float radians) noexcept {
    return static_cast<float>(radians * 180.0 / PI);
}

// consteval for compile-time validation
consteval bool validate_vk_version(uint32_t version) noexcept {
    return VK_API_VERSION_MAJOR(version) >= 1;
}

static_assert(validate_vk_version(VK_API_VERSION_1_3), "Vulkan 1.3+ required");

//=============================================================================
// Error Handling
//=============================================================================

enum class VkErrorCategory : uint8_t {
    Instance,
    Device,
    Swapchain,
    Pipeline,
    Buffer,
    Shader,
    Surface,
    Synchronization,
    Rendering
};

struct VkAppError {
    VkErrorCategory category;
    std::string message;
    vk::Result vk_result{vk::Result::eSuccess};
    std::source_location location;
    
    [[nodiscard]] std::string to_string() const {
        if (vk_result != vk::Result::eSuccess) {
            return std::format("[{}:{}] {} (VkResult: {})",
                location.file_name(), location.line(),
                message, static_cast<int>(vk_result));
        }
        return std::format("[{}:{}] {}",
            location.file_name(), location.line(), message);
    }
};

template<typename T>
using VkResult = std::expected<T, VkAppError>;

#define VK_ERROR(cat, msg) \
    VkAppError{cat, msg, vk::Result::eSuccess, std::source_location::current()}

#define VK_ERROR_RESULT(cat, msg, result) \
    VkAppError{cat, msg, result, std::source_location::current()}

// Helper to convert vk::Result to expected
template<typename T>
constexpr VkResult<T> vk_to_expected(vk::ResultValue<T>&& rv,
                                      VkErrorCategory cat,
                                      std::source_location loc = std::source_location::current()) {
    if (rv.result == vk::Result::eSuccess) {
        return std::move(rv.value);
    }
    return std::unexpected(VkAppError{cat, "Vulkan operation failed", rv.result, loc});
}

//=============================================================================
// RAII Wrappers with Smart Pointers
//=============================================================================

// Deleters for Vulkan resources
struct InstanceDeleter {
    vk::Instance instance;
    void operator()(vk::DebugUtilsMessengerEXT* messenger) const noexcept {
        if (messenger && *messenger) {
            auto destroyer = reinterpret_cast<PFN_vkDestroyDebugUtilsMessengerEXT>(
                instance.getProcAddr("vkDestroyDebugUtilsMessengerEXT"));
            if (destroyer) {
                destroyer(static_cast<VkInstance>(instance), 
                          static_cast<VkDebugUtilsMessengerEXT>(*messenger), nullptr);
            }
            delete messenger;
        }
    }
};

struct SurfaceDeleter {
    vk::Instance instance;
    void operator()(vk::SurfaceKHR* surface) const noexcept {
        if (surface && *surface) {
            instance.destroySurfaceKHR(*surface);
            delete surface;
        }
    }
};

struct DeviceDeleter {
    void operator()(vk::Device* device) const noexcept {
        if (device && *device) {
            device->destroy();
            delete device;
        }
    }
};

struct SwapchainDeleter {
    vk::Device device;
    void operator()(vk::SwapchainKHR* swapchain) const noexcept {
        if (swapchain && *swapchain) {
            device.destroySwapchainKHR(*swapchain);
            delete swapchain;
        }
    }
};

struct PipelineDeleter {
    vk::Device device;
    void operator()(vk::Pipeline* pipeline) const noexcept {
        if (pipeline && *pipeline) {
            device.destroyPipeline(*pipeline);
            delete pipeline;
        }
    }
};

struct PipelineLayoutDeleter {
    vk::Device device;
    void operator()(vk::PipelineLayout* layout) const noexcept {
        if (layout && *layout) {
            device.destroyPipelineLayout(*layout);
            delete layout;
        }
    }
};

struct RenderPassDeleter {
    vk::Device device;
    void operator()(vk::RenderPass* renderPass) const noexcept {
        if (renderPass && *renderPass) {
            device.destroyRenderPass(*renderPass);
            delete renderPass;
        }
    }
};

struct FramebufferDeleter {
    vk::Device device;
    void operator()(vk::Framebuffer* framebuffer) const noexcept {
        if (framebuffer && *framebuffer) {
            device.destroyFramebuffer(*framebuffer);
            delete framebuffer;
        }
    }
};

struct CommandPoolDeleter {
    vk::Device device;
    void operator()(vk::CommandPool* pool) const noexcept {
        if (pool && *pool) {
            device.destroyCommandPool(*pool);
            delete pool;
        }
    }
};

struct BufferDeleter {
    vk::Device device;
    void operator()(vk::Buffer* buffer) const noexcept {
        if (buffer && *buffer) {
            device.destroyBuffer(*buffer);
            delete buffer;
        }
    }
};

struct DeviceMemoryDeleter {
    vk::Device device;
    void operator()(vk::DeviceMemory* memory) const noexcept {
        if (memory && *memory) {
            device.freeMemory(*memory);
            delete memory;
        }
    }
};

struct ImageViewDeleter {
    vk::Device device;
    void operator()(vk::ImageView* view) const noexcept {
        if (view && *view) {
            device.destroyImageView(*view);
            delete view;
        }
    }
};

struct ImageDeleter {
    vk::Device device;
    void operator()(vk::Image* image) const noexcept {
        if (image && *image) {
            device.destroyImage(*image);
            delete image;
        }
    }
};

struct SamplerDeleter {
    vk::Device device;
    void operator()(vk::Sampler* sampler) const noexcept {
        if (sampler && *sampler) {
            device.destroySampler(*sampler);
            delete sampler;
        }
    }
};

struct DescriptorSetLayoutDeleter {
    vk::Device device;
    void operator()(vk::DescriptorSetLayout* layout) const noexcept {
        if (layout && *layout) {
            device.destroyDescriptorSetLayout(*layout);
            delete layout;
        }
    }
};

struct DescriptorPoolDeleter {
    vk::Device device;
    void operator()(vk::DescriptorPool* pool) const noexcept {
        if (pool && *pool) {
            device.destroyDescriptorPool(*pool);
            delete pool;
        }
    }
};

struct FenceDeleter {
    vk::Device device;
    void operator()(vk::Fence* fence) const noexcept {
        if (fence && *fence) {
            device.destroyFence(*fence);
            delete fence;
        }
    }
};

struct SemaphoreDeleter {
    vk::Device device;
    void operator()(vk::Semaphore* sem) const noexcept {
        if (sem && *sem) {
            device.destroySemaphore(*sem);
            delete sem;
        }
    }
};

struct ShaderModuleDeleter {
    vk::Device device;
    void operator()(vk::ShaderModule* module) const noexcept {
        if (module && *module) {
            device.destroyShaderModule(*module);
            delete module;
        }
    }
};

// Smart pointer type aliases
using DebugMessengerPtr = std::unique_ptr<vk::DebugUtilsMessengerEXT, InstanceDeleter>;
using SurfacePtr = std::unique_ptr<vk::SurfaceKHR, SurfaceDeleter>;
using DevicePtr = std::unique_ptr<vk::Device, DeviceDeleter>;
using SwapchainPtr = std::unique_ptr<vk::SwapchainKHR, SwapchainDeleter>;
using PipelinePtr = std::unique_ptr<vk::Pipeline, PipelineDeleter>;
using PipelineLayoutPtr = std::unique_ptr<vk::PipelineLayout, PipelineLayoutDeleter>;
using RenderPassPtr = std::unique_ptr<vk::RenderPass, RenderPassDeleter>;
using FramebufferPtr = std::unique_ptr<vk::Framebuffer, FramebufferDeleter>;
using CommandPoolPtr = std::unique_ptr<vk::CommandPool, CommandPoolDeleter>;
using BufferPtr = std::unique_ptr<vk::Buffer, BufferDeleter>;
using DeviceMemoryPtr = std::unique_ptr<vk::DeviceMemory, DeviceMemoryDeleter>;
using ImageViewPtr = std::unique_ptr<vk::ImageView, ImageViewDeleter>;
using ImagePtr = std::unique_ptr<vk::Image, ImageDeleter>;
using SamplerPtr = std::unique_ptr<vk::Sampler, SamplerDeleter>;
using DescriptorSetLayoutPtr = std::unique_ptr<vk::DescriptorSetLayout, DescriptorSetLayoutDeleter>;
using DescriptorPoolPtr = std::unique_ptr<vk::DescriptorPool, DescriptorPoolDeleter>;
using FencePtr = std::unique_ptr<vk::Fence, FenceDeleter>;
using SemaphorePtr = std::unique_ptr<vk::Semaphore, SemaphoreDeleter>;
using ShaderModulePtr = std::unique_ptr<vk::ShaderModule, ShaderModuleDeleter>;

//=============================================================================
// Vertex Data - constexpr
//=============================================================================

struct Vertex {
    glm::vec3 pos;
    glm::vec3 color;
    glm::vec2 texCoord;
    
    static constexpr vk::VertexInputBindingDescription get_binding_description() {
        return vk::VertexInputBindingDescription{
            .binding = 0,
            .stride = sizeof(Vertex),
            .inputRate = vk::VertexInputRate::eVertex
        };
    }
    
    static constexpr std::array<vk::VertexInputAttributeDescription, 3> 
    get_attribute_descriptions() {
        return {{
            {.location = 0, .binding = 0, .format = vk::Format::eR32G32B32Sfloat,
             .offset = offsetof(Vertex, pos)},
            {.location = 1, .binding = 0, .format = vk::Format::eR32G32B32Sfloat,
             .offset = offsetof(Vertex, color)},
            {.location = 2, .binding = 0, .format = vk::Format::eR32G32Sfloat,
             .offset = offsetof(Vertex, texCoord)}
        }};
    }
};

// consteval cube generation
consteval std::array<Vertex, 36> generate_cube_vertices() noexcept {
    return {{
        // Front face - red
        {{-0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {0.0f, 0.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {1.0f, 1.0f}},
        {{-0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {0.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {1.0f, 1.0f}},
        {{-0.5f,  0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {0.0f, 1.0f}},
        // Back face - green
        {{-0.5f, -0.5f, -0.5f}, {0.0f, 1.0f, 0.0f}, {1.0f, 0.0f}},
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 0.0f}, {1.0f, 1.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 0.0f}, {0.0f, 1.0f}},
        {{-0.5f, -0.5f, -0.5f}, {0.0f, 1.0f, 0.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 0.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f, -0.5f}, {0.0f, 1.0f, 0.0f}, {0.0f, 0.0f}},
        // Top face - blue
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{-0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {0.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {0.0f, 0.0f, 1.0f}, {1.0f, 1.0f}},
        // Bottom face - yellow
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 1.0f, 0.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f, -0.5f}, {1.0f, 1.0f, 0.0f}, {1.0f, 1.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {1.0f, 1.0f, 0.0f}, {1.0f, 0.0f}},
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 1.0f, 0.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {1.0f, 1.0f, 0.0f}, {1.0f, 0.0f}},
        {{-0.5f, -0.5f,  0.5f}, {1.0f, 1.0f, 0.0f}, {0.0f, 0.0f}},
        // Right face - magenta
        {{ 0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {1.0f, 1.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {1.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {1.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 1.0f}, {0.0f, 0.0f}},
        // Left face - cyan
        {{-0.5f, -0.5f, -0.5f}, {0.0f, 1.0f, 1.0f}, {0.0f, 0.0f}},
        {{-0.5f, -0.5f,  0.5f}, {0.0f, 1.0f, 1.0f}, {1.0f, 0.0f}},
        {{-0.5f,  0.5f,  0.5f}, {0.0f, 1.0f, 1.0f}, {1.0f, 1.0f}},
        {{-0.5f, -0.5f, -0.5f}, {0.0f, 1.0f, 1.0f}, {0.0f, 0.0f}},
        {{-0.5f,  0.5f,  0.5f}, {0.0f, 1.0f, 1.0f}, {1.0f, 1.0f}},
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 1.0f}, {0.0f, 1.0f}},
    }};
}

static_assert(generate_cube_vertices().size() == 36);

//=============================================================================
// Uniform Buffer Object
//=============================================================================

struct UniformBufferObject {
    alignas(16) glm::mat4 model;
    alignas(16) glm::mat4 view;
    alignas(16) glm::mat4 proj;
};

//=============================================================================
// Variant-based Configuration
//=============================================================================

struct WindowConfig {
    uint32_t width = 800;
    uint32_t height = 600;
    std::string title = "Vulkan Spinning Cube (C++23)";
    bool fullscreen = false;
};

struct RenderConfig {
    bool wireframe = false;
    bool vsync = true;
    vk::SampleCountFlagBits msaa = vk::SampleCountFlagBits::e4;
    bool enable_validation = true;
};

struct AnimationConfig {
    float rotation_speed_x = 45.0f;
    float rotation_speed_y = 60.0f;
    float rotation_speed_z = 0.0f;
    bool auto_rotate = true;
};

using ConfigVariant = std::variant<WindowConfig, RenderConfig, AnimationConfig>;

struct ConfigPrinter {
    void operator()(const WindowConfig& c) const {
        std::print("Window: {}x{}, title='{}', fullscreen={}\n",
            c.width, c.height, c.title, c.fullscreen);
    }
    void operator()(const RenderConfig& c) const {
        std::print("Render: wireframe={}, vsync={}, msaa={}, validation={}\n",
            c.wireframe, c.vsync, static_cast<int>(c.msaa), c.enable_validation);
    }
    void operator()(const AnimationConfig& c) const {
        std::print("Animation: speed=({},{},{}), auto_rotate={}\n",
            c.rotation_speed_x, c.rotation_speed_y, c.rotation_speed_z, c.auto_rotate);
    }
};

//=============================================================================
// State Machine with Variant
//=============================================================================

struct RunningState {
    float delta_time{0.0f};
    double total_time{0.0};
    uint32_t frame_count{0};
};

struct PausedState {
    double paused_at{0.0};
};

struct ErrorState {
    VkAppError error;
};

using AppState = std::variant<std::monostate, RunningState, PausedState, ErrorState>;

//=============================================================================
// Queue Family Indices
//=============================================================================

struct QueueFamilyIndices {
    std::optional<uint32_t> graphics;
    std::optional<uint32_t> present;
    std::optional<uint32_t> compute;
    
    [[nodiscard]] bool is_complete() const noexcept {
        return graphics.has_value() && present.has_value();
    }
};

//=============================================================================
// Swapchain Support Details
//=============================================================================

struct SwapchainSupport {
    vk::SurfaceCapabilitiesKHR capabilities;
    std::vector<vk::SurfaceFormatKHR> formats;
    std::vector<vk::PresentModeKHR> present_modes;
};

//=============================================================================
// Main Vulkan Application
//=============================================================================

class VulkanCubeApp {
public:
    static VkResult<std::unique_ptr<VulkanCubeApp>> create() {
        auto app = std::make_unique<VulkanCubeApp>();
        
        // Initialize GLFW
        if (!glfwInit()) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Instance, "Failed to init GLFW"));
        }
        glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
        glfwWindowHint(GLFW_RESIZABLE, GLFW_FALSE);
        
        // Create window
        GLFWwindow* window = glfwCreateWindow(
            static_cast<int>(window_config_.width),
            static_cast<int>(window_config_.height),
            window_config_.title.c_str(),
            window_config_.fullscreen ? glfwGetPrimaryMonitor() : nullptr,
            nullptr);
        
        if (!window) {
            glfwTerminate();
            return std::unexpected(VK_ERROR(VkErrorCategory::Surface, "Failed to create window"));
        }
        app->window_ = window;
        glfwSetWindowUserPointer(window, app.get());
        glfwSetKeyCallback(window, key_callback);
        
        // Create Vulkan instance
        VK_TRY(app->create_instance());
        
        // Setup debug messenger
        if (render_config_.enable_validation) {
            VK_TRY(app->setup_debug_messenger());
        }
        
        // Create surface
        VK_TRY(app->create_surface());
        
        // Pick physical device
        VK_TRY(app->pick_physical_device());
        
        // Create logical device
        VK_TRY(app->create_logical_device());
        
        // Create swapchain
        VK_TRY(app->create_swapchain());
        
        // Create image views
        VK_TRY(app->create_image_views());
        
        // Create render pass
        VK_TRY(app->create_render_pass());
        
        // Create descriptor set layout
        VK_TRY(app->create_descriptor_set_layout());
        
        // Create graphics pipeline
        VK_TRY(app->create_graphics_pipeline());
        
        // Create command pool
        VK_TRY(app->create_command_pool());
        
        // Create color resources (MSAA)
        VK_TRY(app->create_color_resources());
        
        // Create depth resources
        VK_TRY(app->create_depth_resources());
        
        // Create framebuffers
        VK_TRY(app->create_framebuffers());
        
        // Create texture
        VK_TRY(app->create_texture_image());
        VK_TRY(app->create_texture_image_view());
        VK_TRY(app->create_texture_sampler());
        
        // Create vertex buffer
        VK_TRY(app->create_vertex_buffer());
        
        // Create uniform buffers
        VK_TRY(app->create_uniform_buffers());
        
        // Create descriptor pool and sets
        VK_TRY(app->create_descriptor_pool());
        VK_TRY(app->create_descriptor_sets());
        
        // Create command buffers
        VK_TRY(app->create_command_buffers());
        
        // Create sync objects
        VK_TRY(app->create_sync_objects());
        
        // Print config
        std::print("=== Configuration ===\n");
        std::visit(ConfigPrinter{}, static_cast<ConfigVariant>(window_config_));
        std::visit(ConfigPrinter{}, static_cast<ConfigVariant>(render_config_));
        std::visit(ConfigPrinter{}, static_cast<ConfigVariant>(animation_config_));
        std::print("=====================\n\n");
        
        return app;
    }
    
    void run() {
        state_ = RunningState{};
        auto last_time = std::chrono::high_resolution_clock::now();
        
        while (!glfwWindowShouldClose(window_)) {
            auto* running = std::get_if<RunningState>(&state_);
            if (!running) {
                if (auto* err = std::get_if<ErrorState>(&state_)) {
                    std::print(stderr, "Error: {}\n", err->error.to_string());
                    break;
                }
                // Paused - just poll events
                glfwPollEvents();
                continue;
            }
            
            auto now = std::chrono::high_resolution_clock::now();
            running->delta_time = std::chrono::duration<float>(now - last_time).count();
            running->total_time += running->delta_time;
            running->frame_count++;
            last_time = now;
            
            update(*running);
            
            auto draw_result = draw_frame();
            if (!draw_result) {
                state_ = ErrorState{draw_result.error()};
            }
            
            glfwPollEvents();
        }
        
        // Wait for device to finish
        if (device_) {
            device_->waitIdle();
        }
    }
    
    ~VulkanCubeApp() {
        cleanup();
        if (window_) {
            glfwDestroyWindow(window_);
            glfwTerminate();
        }
    }
    
    // Non-copyable, movable
    VulkanCubeApp(const VulkanCubeApp&) = delete;
    VulkanCubeApp& operator=(const VulkanCubeApp&) = delete;
    VulkanCubeApp(VulkanCubeApp&&) = default;
    VulkanCubeApp& operator=(VulkanCubeApp&&) = default;
    
private:
    VulkanCubeApp() = default;
    
    void cleanup() {
        // Smart pointers handle most cleanup automatically
        // Just need to handle vectors
        uniform_buffers_.clear();
        uniform_buffers_memory_.clear();
        command_buffers_.clear();
        swapchain_framebuffers_.clear();
        swapchain_image_views_.clear();
    }
    
    //-------------------------------------------------------------------------
    // Instance Creation
    //-------------------------------------------------------------------------
    
    VkResult<void> create_instance() {
        vk::ApplicationInfo app_info{
            .pApplicationName = "Vulkan Cube",
            .applicationVersion = VK_MAKE_API_VERSION(0, 1, 0, 0),
            .pEngineName = "No Engine",
            .engineVersion = VK_MAKE_API_VERSION(0, 1, 0, 0),
            .apiVersion = VK_API_VERSION_1_3
        };
        
        auto extensions = get_required_extensions();
        
        vk::InstanceCreateInfo create_info{
            .pApplicationInfo = &app_info,
        };
        
        // Validation layers
        if (render_config_.enable_validation) {
            consteval std::array<const char*, 1> validation_layers = {
                "VK_LAYER_KHRONOS_validation"
            };
            create_info.setLayerCount(validation_layers.size());
            create_info.setPPEnabledLayerNames(validation_layers.data());
        }
        
        create_info.setEnabledExtensionCount(static_cast<uint32_t>(extensions.size()));
        create_info.setPpEnabledExtensionNames(extensions.data());
        
        auto result = vk::createInstance(&create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Instance, 
                "Failed to create instance", result.result));
        }
        
        instance_ = std::move(result.value);
        instance_.loadDelegates();
        
        return {};
    }
    
    std::vector<const char*> get_required_extensions() const {
        uint32_t glfw_ext_count = 0;
        const char** glfw_extensions = glfwGetRequiredInstanceExtensions(&glfw_ext_count);
        
        std::vector<const char*> extensions(glfw_extensions, glfw_extensions + glfw_ext_count);
        
        if (render_config_.enable_validation) {
            extensions.push_back(VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
        }
        
        return extensions;
    }
    
    //-------------------------------------------------------------------------
    // Debug Messenger
    //-------------------------------------------------------------------------
    
    static VKAPI_ATTR VkBool32 VKAPI_CALL debug_callback(
        VkDebugUtilsMessageSeverityFlagBitsEXT message_severity,
        VkDebugUtilsMessageTypeFlagsEXT message_type,
        const VkDebugUtilsMessengerCallbackDataEXT* callback_data,
        void* user_data) 
    {
        auto severity = vk::DebugUtilsMessageSeverityFlagBitsEXT(message_severity);
        if (severity >= vk::DebugUtilsMessageSeverityFlagBitsEXT::eWarning) {
            std::print(stderr, "[Validation] {}\n", callback_data->pMessage);
        }
        return VK_FALSE;
    }
    
    VkResult<void> setup_debug_messenger() {
        vk::DebugUtilsMessengerCreateInfoEXT create_info{
            .messageSeverity = vk::DebugUtilsMessageSeverityFlagBitsEXT::eWarning |
                               vk::DebugUtilsMessageSeverityFlagBitsEXT::eError,
            .messageType = vk::DebugUtilsMessageTypeFlagBitsEXT::eGeneral |
                           vk::DebugUtilsMessageTypeFlagBitsEXT::eValidation |
                           vk::DebugUtilsMessageTypeFlagBitsEXT::ePerformance,
            .pfnUserCallback = debug_callback
        };
        
        auto result = instance_.createDebugUtilsMessengerEXT(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Instance,
                "Failed to setup debug messenger", result.result));
        }
        
        debug_messenger_ = DebugMessengerPtr(
            new vk::DebugUtilsMessengerEXT(std::move(result.value)),
            InstanceDeleter{instance_}
        );
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Surface
    //-------------------------------------------------------------------------
    
    VkResult<void> create_surface() {
        VkSurfaceKHR surface;
        if (glfwCreateWindowSurface(instance_, window_, nullptr, &surface) != VK_SUCCESS) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Surface, "Failed to create surface"));
        }
        
        surface_ = SurfacePtr(
            new vk::SurfaceKHR(surface),
            SurfaceDeleter{instance_}
        );
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Physical Device
    //-------------------------------------------------------------------------
    
    VkResult<void> pick_physical_device() {
        auto devices = instance_.enumeratePhysicalDevices();
        if (devices.result != vk::Result::eSuccess || devices.value.empty()) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Device, "No GPUs found"));
        }
        
        // Use ranges and algorithms (C++20/23)
        auto suitable = devices.value | 
            std::views::filter([this](const vk::PhysicalDevice& d) { 
                return is_device_suitable(d); 
            });
        
        auto it = std::ranges::find_if(suitable, [](const vk::PhysicalDevice& d) {
            auto props = d.getProperties();
            return props.deviceType == vk::PhysicalDeviceType::eDiscreteGpu;
        });
        
        if (it == suitable.end()) {
            it = suitable.begin();
        }
        
        if (it == suitable.end()) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Device, "No suitable GPU"));
        }
        
        physical_device_ = *it;
        
        auto props = physical_device_.getProperties();
        std::print("Selected GPU: {}\n", props.deviceName);
        
        return {};
    }
    
    bool is_device_suitable(vk::PhysicalDevice device) const {
        auto indices = find_queue_families(device);
        if (!indices.is_complete()) return false;
        
        auto extensions_supported = check_device_extension_support(device);
        if (!extensions_supported) return false;
        
        auto swapchain_support = query_swapchain_support(device);
        if (swapchain_support.formats.empty() || swapchain_support.present_modes.empty()) {
            return false;
        }
        
        return true;
    }
    
    QueueFamilyIndices find_queue_families(vk::PhysicalDevice device) const {
        QueueFamilyIndices indices;
        auto queues = device.getQueueFamilyProperties();
        
        for (uint32_t i = 0; i < queues.size(); ++i) {
            const auto& queue = queues[i];
            
            if (queue.queueFlags & vk::QueueFlagBits::eGraphics) {
                indices.graphics = i;
            }
            
            if (device.getSurfaceSupportKHR(i, *surface_)) {
                indices.present = i;
            }
            
            if (queue.queueFlags & vk::QueueFlagBits::eCompute) {
                indices.compute = i;
            }
        }
        
        return indices;
    }
    
    bool check_device_extension_support(vk::PhysicalDevice device) const {
        consteval std::array device_extensions = {
            VK_KHR_SWAPCHAIN_EXTENSION_NAME
        };
        
        auto available = device.enumerateDeviceExtensionProperties();
        if (available.result != vk::Result::eSuccess) return false;
        
        for (const auto& required : device_extensions) {
            bool found = std::ranges::any_of(available.value, 
                [&required](const vk::ExtensionProperties& ext) {
                    return std::string_view(ext.extensionName) == required;
                });
            if (!found) return false;
        }
        
        return true;
    }
    
    SwapchainSupport query_swapchain_support(vk::PhysicalDevice device) const {
        SwapchainSupport support;
        support.capabilities = device.getSurfaceCapabilitiesKHR(*surface_).value;
        support.formats = device.getSurfaceFormatsKHR(*surface_).value;
        support.present_modes = device.getSurfacePresentModesKHR(*surface_).value;
        return support;
    }
    
    //-------------------------------------------------------------------------
    // Logical Device
    //-------------------------------------------------------------------------
    
    VkResult<void> create_logical_device() {
        queue_indices_ = find_queue_families(physical_device_);
        
        std::vector<vk::DeviceQueueCreateInfo> queue_create_infos;
        std::set<uint32_t> unique_queue_families = {
            *queue_indices_.graphics, *queue_indices_.present
        };
        
        constexpr float queue_priority = 1.0f;
        for (uint32_t family : unique_queue_families) {
            queue_create_infos.push_back({
                .queueFamilyIndex = family,
                .queueCount = 1,
                .pQueuePriorities = &queue_priority
            });
        }
        
        vk::DeviceCreateInfo create_info{
            .queueCreateInfoCount = static_cast<uint32_t>(queue_create_infos.size()),
            .pQueueCreateInfos = queue_create_infos.data(),
        };
        
        consteval std::array device_extensions = {
            VK_KHR_SWAPCHAIN_EXTENSION_NAME
        };
        create_info.setEnabledExtensionCount(device_extensions.size());
        create_info.setPpEnabledExtensionNames(device_extensions.data());
        
        vk::PhysicalDeviceFeatures device_features{
            .samplerAnisotropy = VK_TRUE,
            .fillModeNonSolid = VK_TRUE  // For wireframe
        };
        create_info.setPEnabledFeatures(&device_features);
        
        if (render_config_.enable_validation) {
            consteval std::array<const char*, 1> layers = {"VK_LAYER_KHRONOS_validation"};
            create_info.setEnabledLayerCount(layers.size());
            create_info.setPpEnabledLayerNames(layers.data());
        }
        
        auto result = physical_device_.createDevice(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Device,
                "Failed to create logical device", result.result));
        }
        
        device_ = DevicePtr(new vk::Device(std::move(result.value)));
        device_->loadDelegates();
        
        graphics_queue_ = device_->getQueue(*queue_indices_.graphics, 0);
        present_queue_ = device_->getQueue(*queue_indices_.present, 0);
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Swapchain
    //-------------------------------------------------------------------------
    
    VkResult<void> create_swapchain() {
        auto support = query_swapchain_support(physical_device_);
        
        auto surface_format = choose_swap_surface_format(support.formats);
        auto present_mode = choose_swap_present_mode(support.present_modes);
        auto extent = choose_swap_extent(support.capabilities);
        
        uint32_t image_count = support.capabilities.minImageCount + 1;
        if (support.capabilities.maxImageCount > 0 && 
            image_count > support.capabilities.maxImageCount) {
            image_count = support.capabilities.maxImageCount;
        }
        
        vk::SwapchainCreateInfoKHR create_info{
            .surface = *surface_,
            .minImageCount = image_count,
            .imageFormat = surface_format.format,
            .imageColorSpace = surface_format.colorSpace,
            .imageExtent = extent,
            .imageArrayLayers = 1,
            .imageUsage = vk::ImageUsageFlagBits::eColorAttachment,
            .preTransform = support.capabilities.currentTransform,
            .compositeAlpha = vk::CompositeAlphaFlagBitsKHR::eOpaque,
            .presentMode = present_mode,
            .clipped = VK_TRUE,
        };
        
        if (*queue_indices_.graphics != *queue_indices_.present) {
            create_info.imageSharingMode = vk::SharingMode::eConcurrent;
            create_info.queueFamilyIndexCount = 2;
            const std::array indices = {*queue_indices_.graphics, *queue_indices_.present};
            create_info.setPQueueFamilyIndices(indices);
        } else {
            create_info.imageSharingMode = vk::SharingMode::eExclusive;
        }
        
        auto result = device_->createSwapchainKHR(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Swapchain,
                "Failed to create swapchain", result.result));
        }
        
        swapchain_ = SwapchainPtr(
            new vk::SwapchainKHR(std::move(result.value)),
            SwapchainDeleter{*device_}
        );
        
        swapchain_images_ = device_->getSwapchainImagesKHR(*swapchain_).value;
        swapchain_image_format_ = surface_format.format;
        swapchain_extent_ = extent;
        
        return {};
    }
    
    static vk::SurfaceFormatKHR choose_swap_surface_format(
        const std::vector<vk::SurfaceFormatKHR>& formats) 
    {
        for (const auto& format : formats) {
            if (format.format == vk::Format::eB8G8R8A8Srgb &&
                format.colorSpace == vk::ColorSpaceKHR::eSrgbNonlinear) {
                return format;
            }
        }
        return formats[0];
    }
    
    static vk::PresentModeKHR choose_swap_present_mode(
        const std::vector<vk::PresentModeKHR>& present_modes)
    {
        for (const auto& mode : present_modes) {
            if (mode == vk::PresentModeKHR::eMailbox) {
                return mode;
            }
        }
        return vk::PresentModeKHR::eFifo;
    }
    
    vk::Extent2D choose_swap_extent(const vk::SurfaceCapabilitiesKHR& capabilities) const {
        if (capabilities.currentExtent.width != std::numeric_limits<uint32_t>::max()) {
            return capabilities.currentExtent;
        }
        
        int width, height;
        glfwGetFramebufferSize(window_, &width, &height);
        
        vk::Extent2D extent = {
            static_cast<uint32_t>(width),
            static_cast<uint32_t>(height)
        };
        
        extent.width = std::clamp(extent.width, 
            capabilities.minImageExtent.width, capabilities.maxImageExtent.width);
        extent.height = std::clamp(extent.height,
            capabilities.minImageExtent.height, capabilities.maxImageExtent.height);
        
        return extent;
    }
    
    //-------------------------------------------------------------------------
    // Image Views
    //-------------------------------------------------------------------------
    
    VkResult<void> create_image_views() {
        swapchain_image_views_.reserve(swapchain_images_.size());
        
        for (const auto& image : swapchain_images_) {
            vk::ImageViewCreateInfo create_info{
                .image = image,
                .viewType = vk::ImageViewType::e2D,
                .format = swapchain_image_format_,
                .components = {
                    .r = vk::ComponentSwizzle::eIdentity,
                    .g = vk::ComponentSwizzle::eIdentity,
                    .b = vk::ComponentSwizzle::eIdentity,
                    .a = vk::ComponentSwizzle::eIdentity
                },
                .subresourceRange = {
                    .aspectMask = vk::ImageAspectFlagBits::eColor,
                    .baseMipLevel = 0,
                    .levelCount = 1,
                    .baseArrayLayer = 0,
                    .layerCount = 1
                }
            };
            
            auto result = device_->createImageView(create_info, nullptr);
            if (result.result != vk::Result::eSuccess) {
                return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Swapchain,
                    "Failed to create image view", result.result));
            }
            
            swapchain_image_views_.push_back(ImageViewPtr(
                new vk::ImageView(std::move(result.value)),
                ImageViewDeleter{*device_}
            ));
        }
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Render Pass
    //-------------------------------------------------------------------------
    
    VkResult<void> create_render_pass() {
        vk::AttachmentDescription color_attachment{
            .format = swapchain_image_format_,
            .samples = render_config_.msaa,
            .loadOp = vk::AttachmentLoadOp::eClear,
            .storeOp = vk::AttachmentStoreOp::eStore,
            .stencilLoadOp = vk::AttachmentLoadOp::eDontCare,
            .stencilStoreOp = vk::AttachmentStoreOp::eDontCare,
            .initialLayout = vk::ImageLayout::eUndefined,
            .finalLayout = vk::ImageLayout::eColorAttachmentOptimal
        };
        
        vk::AttachmentDescription depth_attachment{
            .format = find_depth_format(),
            .samples = render_config_.msaa,
            .loadOp = vk::AttachmentLoadOp::eClear,
            .storeOp = vk::AttachmentStoreOp::eDontCare,
            .stencilLoadOp = vk::AttachmentLoadOp::eDontCare,
            .stencilStoreOp = vk::AttachmentStoreOp::eDontCare,
            .initialLayout = vk::ImageLayout::eUndefined,
            .finalLayout = vk::ImageLayout::eDepthStencilAttachmentOptimal
        };
        
        vk::AttachmentDescription color_resolve_attachment{
            .format = swapchain_image_format_,
            .samples = vk::SampleCountFlagBits::e1,
            .loadOp = vk::AttachmentLoadOp::eDontCare,
            .storeOp = vk::AttachmentStoreOp::eStore,
            .stencilLoadOp = vk::AttachmentLoadOp::eDontCare,
            .stencilStoreOp = vk::AttachmentStoreOp::eDontCare,
            .initialLayout = vk::ImageLayout::eUndefined,
            .finalLayout = vk::ImageLayout::ePresentSrcKHR
        };
        
        vk::AttachmentReference color_ref{
            .attachment = 0,
            .layout = vk::ImageLayout::eColorAttachmentOptimal
        };
        
        vk::AttachmentReference depth_ref{
            .attachment = 1,
            .layout = vk::ImageLayout::eDepthStencilAttachmentOptimal
        };
        
        vk::AttachmentReference color_resolve_ref{
            .attachment = 2,
            .layout = vk::ImageLayout::eColorAttachmentOptimal
        };
        
        vk::SubpassDescription subpass{
            .pipelineBindPoint = vk::PipelineBindPoint::eGraphics,
            .colorAttachmentCount = 1,
            .pColorAttachments = &color_ref,
            .pResolveAttachments = &color_resolve_ref,
            .pDepthStencilAttachment = &depth_ref
        };
        
        vk::SubpassDependency dependency{
            .srcSubpass = VK_SUBPASS_EXTERNAL,
            .dstSubpass = 0,
            .srcStageMask = vk::PipelineStageFlagBits::eColorAttachmentOutput |
                            vk::PipelineStageFlagBits::eEarlyFragmentTests,
            .dstStageMask = vk::PipelineStageFlagBits::eColorAttachmentOutput |
                            vk::PipelineStageFlagBits::eEarlyFragmentTests,
            .srcAccessMask = {},
            .dstAccessMask = vk::AccessFlagBits::eColorAttachmentWrite |
                             vk::AccessFlagBits::eDepthStencilAttachmentWrite
        };
        
        std::array attachments = {color_attachment, depth_attachment, color_resolve_attachment};
        
        vk::RenderPassCreateInfo create_info{
            .attachmentCount = static_cast<uint32_t>(attachments.size()),
            .pAttachments = attachments.data(),
            .subpassCount = 1,
            .pSubpasses = &subpass,
            .dependencyCount = 1,
            .pDependencies = &dependency
        };
        
        auto result = device_->createRenderPass(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Pipeline,
                "Failed to create render pass", result.result));
        }
        
        render_pass_ = RenderPassPtr(
            new vk::RenderPass(std::move(result.value)),
            RenderPassDeleter{*device_}
        );
        
        return {};
    }
    
    vk::Format find_depth_format() const {
        consteval std::array candidates = {
            vk::Format::eD32SfloatS8Uint,
            vk::Format::eD32Sfloat,
            vk::Format::eD24UnormS8Uint
        };
        
        for (vk::Format format : candidates) {
            auto props = physical_device_.getFormatProperties(format);
            if (props.optimalTilingFeatures & vk::FormatFeatureFlagBits::eDepthStencilAttachment) {
                return format;
            }
        }
        
        return vk::Format::eD32Sfloat;
    }
    
    //-------------------------------------------------------------------------
    // Descriptor Set Layout
    //-------------------------------------------------------------------------
    
    VkResult<void> create_descriptor_set_layout() {
        std::array bindings = {
            vk::DescriptorSetLayoutBinding{
                .binding = 0,
                .descriptorType = vk::DescriptorType::eUniformBuffer,
                .descriptorCount = 1,
                .stageFlags = vk::ShaderStageFlagBits::eVertex,
                .pImmutableSamplers = nullptr
            },
            vk::DescriptorSetLayoutBinding{
                .binding = 1,
                .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                .descriptorCount = 1,
                .stageFlags = vk::ShaderStageFlagBits::eFragment,
                .pImmutableSamplers = nullptr
            }
        };
        
        vk::DescriptorSetLayoutCreateInfo create_info{
            .bindingCount = static_cast<uint32_t>(bindings.size()),
            .pBindings = bindings.data()
        };
        
        auto result = device_->createDescriptorSetLayout(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Pipeline,
                "Failed to create descriptor set layout", result.result));
        }
        
        descriptor_set_layout_ = DescriptorSetLayoutPtr(
            new vk::DescriptorSetLayout(std::move(result.value)),
            DescriptorSetLayoutDeleter{*device_}
        );
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Graphics Pipeline
    //-------------------------------------------------------------------------
    
    VkResult<void> create_graphics_pipeline() {
        // Shader modules
        VK_TRY(create_shader_module(vertex_shader_spv(), vertex_shader_module_));
        VK_TRY(create_shader_module(fragment_shader_spv(), fragment_shader_module_));
        
        std::array shader_stages = {
            vk::PipelineShaderStageCreateInfo{
                .stage = vk::ShaderStageFlagBits::eVertex,
                .module = *vertex_shader_module_,
                .pName = "main"
            },
            vk::PipelineShaderStageCreateInfo{
                .stage = vk::ShaderStageFlagBits::eFragment,
                .module = *fragment_shader_module_,
                .pName = "main"
            }
        };
        
        auto binding_desc = Vertex::get_binding_description();
        auto attr_descs = Vertex::get_attribute_descriptions();
        
        vk::PipelineVertexInputStateCreateInfo vertex_input{
            .vertexBindingDescriptionCount = 1,
            .pVertexBindingDescriptions = &binding_desc,
            .vertexAttributeDescriptionCount = static_cast<uint32_t>(attr_descs.size()),
            .pVertexAttributeDescriptions = attr_descs.data()
        };
        
        vk::PipelineInputAssemblyStateCreateInfo input_assembly{
            .topology = vk::PrimitiveTopology::eTriangleList,
            .primitiveRestartEnable = VK_FALSE
        };
        
        vk::PipelineViewportStateCreateInfo viewport_state{
            .viewportCount = 1,
            .scissorCount = 1,
        };
        
        vk::PipelineRasterizationStateCreateInfo rasterizer{
            .depthClampEnable = VK_FALSE,
            .rasterizerDiscardEnable = VK_FALSE,
            .polygonMode = render_config_.wireframe ? 
                vk::PolygonMode::eLine : vk::PolygonMode::eFill,
            .cullMode = vk::CullModeFlagBits::eBack,
            .frontFace = vk::FrontFace::eCounterClockwise,
            .depthBiasEnable = VK_FALSE,
            .lineWidth = 1.0f
        };
        
        vk::PipelineMultisampleStateCreateInfo multisampling{
            .rasterizationSamples = render_config_.msaa,
            .sampleShadingEnable = VK_TRUE,
            .minSampleShading = 0.2f
        };
        
        vk::PipelineDepthStencilStateCreateInfo depth_stencil{
            .depthTestEnable = VK_TRUE,
            .depthWriteEnable = VK_TRUE,
            .depthCompareOp = vk::CompareOp::eLess,
            .depthBoundsTestEnable = VK_FALSE,
            .stencilTestEnable = VK_FALSE,
        };
        
        vk::PipelineColorBlendAttachmentState color_blend_attachment{
            .blendEnable = VK_TRUE,
            .srcColorBlendFactor = vk::BlendFactor::eSrcAlpha,
            .dstColorBlendFactor = vk::BlendFactor::eOneMinusSrcAlpha,
            .colorBlendOp = vk::BlendOp::eAdd,
            .srcAlphaBlendFactor = vk::BlendFactor::eOne,
            .dstAlphaBlendFactor = vk::BlendFactor::eZero,
            .alphaBlendOp = vk::BlendOp::eAdd,
            .colorWriteMask = vk::ColorComponentFlagBits::eR |
                               vk::ColorComponentFlagBits::eG |
                               vk::ColorComponentFlagBits::eB |
                               vk::ColorComponentFlagBits::eA
        };
        
        vk::PipelineColorBlendStateCreateInfo color_blending{
            .logicOpEnable = VK_FALSE,
            .attachmentCount = 1,
            .pAttachments = &color_blend_attachment,
        };
        
        std::array dynamic_states = {
            vk::DynamicState::eViewport,
            vk::DynamicState::eScissor
        };
        
        vk::PipelineDynamicStateCreateInfo dynamic_state{
            .dynamicStateCount = static_cast<uint32_t>(dynamic_states.size()),
            .pDynamicStates = dynamic_states.data()
        };
        
        vk::PipelineLayoutCreateInfo pipeline_layout_info{
            .setLayoutCount = 1,
            .pSetLayouts = &*descriptor_set_layout_,
        };
        
        auto layout_result = device_->createPipelineLayout(pipeline_layout_info, nullptr);
        if (layout_result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Pipeline,
                "Failed to create pipeline layout", layout_result.result));
        }
        
        pipeline_layout_ = PipelineLayoutPtr(
            new vk::PipelineLayout(std::move(layout_result.value)),
            PipelineLayoutDeleter{*device_}
        );
        
        vk::GraphicsPipelineCreateInfo pipeline_info{
            .stageCount = static_cast<uint32_t>(shader_stages.size()),
            .pStages = shader_stages.data(),
            .pVertexInputState = &vertex_input,
            .pInputAssemblyState = &input_assembly,
            .pViewportState = &viewport_state,
            .pRasterizationState = &rasterizer,
            .pMultisampleState = &multisampling,
            .pDepthStencilState = &depth_stencil,
            .pColorBlendState = &color_blending,
            .pDynamicState = &dynamic_state,
            .layout = *pipeline_layout_,
            .renderPass = *render_pass_,
            .subpass = 0,
        };
        
        auto pipeline_result = device_->createGraphicsPipeline(nullptr, pipeline_info);
        if (pipeline_result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Pipeline,
                "Failed to create graphics pipeline", pipeline_result.result));
        }
        
        graphics_pipeline_ = PipelinePtr(
            new vk::Pipeline(std::move(pipeline_result.value)),
            PipelineDeleter{*device_}
        );
        
        return {};
    }
    
    VkResult<void> create_shader_module(std::span<const uint32_t> code, 
                                         ShaderModulePtr& module) {
        vk::ShaderModuleCreateInfo create_info{
            .codeSize = code.size() * sizeof(uint32_t),
            .pCode = code.data()
        };
        
        auto result = device_->createShaderModule(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Shader,
                "Failed to create shader module", result.result));
        }
        
        module = ShaderModulePtr(
            new vk::ShaderModule(std::move(result.value)),
            ShaderModuleDeleter{*device_}
        );
        
        return {};
    }
    
    // Inline SPIR-V (pre-compiled)
    static consteval std::array<uint32_t, 300> vertex_shader_spv() noexcept {
        // This is a placeholder - in real code, use glslang to compile
        // For now, return empty and we'll fail gracefully
        // In production, embed actual SPIR-V here using xxd -i
        return {};
    }
    
    static consteval std::array<uint32_t, 200> fragment_shader_spv() noexcept {
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Command Pool
    //-------------------------------------------------------------------------
    
    VkResult<void> create_command_pool() {
        vk::CommandPoolCreateInfo create_info{
            .flags = vk::CommandPoolCreateFlagBits::eResetCommandBuffer,
            .queueFamilyIndex = *queue_indices_.graphics
        };
        
        auto result = device_->createCommandPool(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Rendering,
                "Failed to create command pool", result.result));
        }
        
        command_pool_ = CommandPoolPtr(
            new vk::CommandPool(std::move(result.value)),
            CommandPoolDeleter{*device_}
        );
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Color Resources (MSAA)
    //-------------------------------------------------------------------------
    
    VkResult<void> create_color_resources() {
        vk::Format color_format = swapchain_image_format_;
        
        VK_TRY(create_image(
            swapchain_extent_.width, swapchain_extent_.height,
            color_format, vk::ImageTiling::eOptimal,
            vk::ImageUsageFlagBits::eTransientAttachment | 
            vk::ImageUsageFlagBits::eColorAttachment,
            render_config_.msaa, vk::MemoryPropertyFlagBits::eDeviceLocal,
            color_image_, color_image_memory_
        ));
        
        VK_TRY(create_image_view(
            *color_image_, color_format, vk::ImageAspectFlagBits::eColor,
            color_image_view_
        ));
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Depth Resources
    //-------------------------------------------------------------------------
    
    VkResult<void> create_depth_resources() {
        vk::Format depth_format = find_depth_format();
        
        VK_TRY(create_image(
            swapchain_extent_.width, swapchain_extent_.height,
            depth_format, vk::ImageTiling::eOptimal,
            vk::ImageUsageFlagBits::eDepthStencilAttachment,
            render_config_.msaa, vk::MemoryPropertyFlagBits::eDeviceLocal,
            depth_image_, depth_image_memory_
        ));
        
        VK_TRY(create_image_view(
            *depth_image_, depth_format, vk::ImageAspectFlagBits::eDepth,
            depth_image_view_
        ));
        
        return {};
    }
    
    VkResult<void> create_image(
        uint32_t width, uint32_t height,
        vk::Format format, vk::ImageTiling tiling,
        vk::ImageUsageFlags usage, vk::SampleCountFlagBits samples,
        vk::MemoryPropertyFlags properties,
        ImagePtr& image, DeviceMemoryPtr& memory)
    {
        vk::ImageCreateInfo image_info{
            .imageType = vk::ImageType::e2D,
            .format = format,
            .extent = {width, height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = samples,
            .tiling = tiling,
            .usage = usage,
            .sharingMode = vk::SharingMode::eExclusive,
            .initialLayout = vk::ImageLayout::eUndefined
        };
        
        auto img_result = device_->createImage(image_info, nullptr);
        if (img_result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Buffer,
                "Failed to create image", img_result.result));
        }
        
        image = ImagePtr(
            new vk::Image(std::move(img_result.value)),
            ImageDeleter{*device_}
        );
        
        auto mem_reqs = device_->getImageMemoryRequirements(*image);
        
        VK_TRY(allocate_memory(mem_reqs, properties, memory));
        device_->bindImageMemory(*image, *memory, 0);
        
        return {};
    }
    
    VkResult<void> create_image_view(
        vk::Image image, vk::Format format,
        vk::ImageAspectFlags aspect_flags, ImageViewPtr& view)
    {
        vk::ImageViewCreateInfo create_info{
            .image = image,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .components = {
                .r = vk::ComponentSwizzle::eIdentity,
                .g = vk::ComponentSwizzle::eIdentity,
                .b = vk::ComponentSwizzle::eIdentity,
                .a = vk::ComponentSwizzle::eIdentity
            },
            .subresourceRange = {
                .aspectMask = aspect_flags,
                .baseMipLevel = 0,
                .levelCount = 1,
                .baseArrayLayer = 0,
                .layerCount = 1
            }
        };
        
        auto result = device_->createImageView(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Buffer,
                "Failed to create image view", result.result));
        }
        
        view = ImageViewPtr(
            new vk::ImageView(std::move(result.value)),
            ImageViewDeleter{*device_}
        );
        
        return {};
    }
    
    VkResult<void> allocate_memory(
        const vk::MemoryRequirements& reqs,
        vk::MemoryPropertyFlags properties,
        DeviceMemoryPtr& memory)
    {
        auto mem_props = physical_device_.getMemoryProperties();
        
        uint32_t mem_type = std::numeric_limits<uint32_t>::max();
        for (uint32_t i = 0; i < mem_props.memoryTypeCount; ++i) {
            if ((reqs.memoryTypeBits & (1 << i)) &&
                (mem_props.memoryTypes[i].propertyFlags & properties) == properties) {
                mem_type = i;
                break;
            }
        }
        
        if (mem_type == std::numeric_limits<uint32_t>::max()) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Buffer, 
                "Failed to find suitable memory type"));
        }
        
        vk::MemoryAllocateInfo alloc_info{
            .allocationSize = reqs.size,
            .memoryTypeIndex = mem_type
        };
        
        auto result = device_->allocateMemory(alloc_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Buffer,
                "Failed to allocate memory", result.result));
        }
        
        memory = DeviceMemoryPtr(
            new vk::DeviceMemory(std::move(result.value)),
            DeviceMemoryDeleter{*device_}
        );
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Framebuffers
    //-------------------------------------------------------------------------
    
    VkResult<void> create_framebuffers() {
        swapchain_framebuffers_.reserve(swapchain_image_views_.size());
        
        for (size_t i = 0; i < swapchain_image_views_.size(); ++i) {
            std::array attachments = {
                *color_image_view_,
                *depth_image_view_,
                *swapchain_image_views_[i]
            };
            
            vk::FramebufferCreateInfo create_info{
                .renderPass = *render_pass_,
                .attachmentCount = static_cast<uint32_t>(attachments.size()),
                .pAttachments = attachments.data(),
                .width = swapchain_extent_.width,
                .height = swapchain_extent_.height,
                .layers = 1
            };
            
            auto result = device_->createFramebuffer(create_info, nullptr);
            if (result.result != vk::Result::eSuccess) {
                return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Swapchain,
                    "Failed to create framebuffer", result.result));
            }
            
            swapchain_framebuffers_.push_back(FramebufferPtr(
                new vk::Framebuffer(std::move(result.value)),
                FramebufferDeleter{*device_}
            ));
        }
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Texture
    //-------------------------------------------------------------------------
    
    VkResult<void> create_texture_image() {
        constexpr uint32_t tex_width = 8;
        constexpr uint32_t tex_height = 8;
        
        // Generate checkerboard
        consteval auto make_checkerboard() {
            std::array<uint32_t, tex_width * tex_height> pixels{};
            for (uint32_t y = 0; y < tex_height; ++y) {
                for (uint32_t x = 0; x < tex_width; ++x) {
                    bool white = (x + y) % 2 == 0;
                    // ABGR format
                    pixels[y * tex_width + x] = white ? 0xFFFFFFFF : 0xFF333333;
                }
            }
            return pixels;
        }
        
        constexpr auto pixels = make_checkerboard();
        constexpr vk::DeviceSize image_size = sizeof(pixels);
        
        // Staging buffer
        BufferPtr staging_buffer;
        DeviceMemoryPtr staging_memory;
        
        VK_TRY(create_buffer(
            image_size, 
            vk::BufferUsageFlagBits::eTransferSrc,
            vk::MemoryPropertyFlagBits::eHostVisible | 
            vk::MemoryPropertyFlagBits::eHostCoherent,
            staging_buffer, staging_memory
        ));
        
        // Copy data to staging buffer
        void* data = device_->mapMemory(*staging_memory, 0, image_size);
        std::memcpy(data, pixels.data(), image_size);
        device_->unmapMemory(*staging_memory);
        
        // Create texture image
        VK_TRY(create_image(
            tex_width, tex_height,
            vk::Format::eR8G8B8A8Unorm,
            vk::ImageTiling::eOptimal,
            vk::ImageUsageFlagBits::eTransferDst | vk::ImageUsageFlagBits::eSampled,
            vk::SampleCountFlagBits::e1,
            vk::MemoryPropertyFlagBits::eDeviceLocal,
            texture_image_, texture_image_memory_
        ));
        
        // Transition and copy
        VK_TRY(transition_image_layout(
            *texture_image_, vk::Format::eR8G8B8A8Unorm,
            vk::ImageLayout::eUndefined, vk::ImageLayout::eTransferDstOptimal
        ));
        
        copy_buffer_to_image(*staging_buffer, *texture_image_, tex_width, tex_height);
        
        VK_TRY(transition_image_layout(
            *texture_image_, vk::Format::eR8G8B8A8Unorm,
            vk::ImageLayout::eTransferDstOptimal, vk::ImageLayout::eShaderReadOnlyOptimal
        ));
        
        return {};
    }
    
    VkResult<void> create_texture_image_view() {
        return create_image_view(
            *texture_image_, vk::Format::eR8G8B8A8Unorm,
            vk::ImageAspectFlagBits::eColor,
            texture_image_view_
        );
    }
    
    VkResult<void> create_texture_sampler() {
        vk::PhysicalDeviceProperties props = physical_device_.getProperties();
        
        vk::SamplerCreateInfo create_info{
            .magFilter = vk::Filter::eNearest,
            .minFilter = vk::Filter::eNearest,
            .mipmapMode = vk::SamplerMipmapMode::eNearest,
            .addressModeU = vk::SamplerAddressMode::eRepeat,
            .addressModeV = vk::SamplerAddressMode::eRepeat,
            .addressModeW = vk::SamplerAddressMode::eRepeat,
            .mipLodBias = 0.0f,
            .anisotropyEnable = VK_TRUE,
            .maxAnisotropy = props.limits.maxSamplerAnisotropy,
            .compareEnable = VK_FALSE,
            .compareOp = vk::CompareOp::eAlways,
            .minLod = 0.0f,
            .maxLod = 0.0f,
            .borderColor = vk::BorderColor::eIntOpaqueBlack,
            .unnormalizedCoordinates = VK_FALSE
        };
        
        auto result = device_->createSampler(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Buffer,
                "Failed to create sampler", result.result));
        }
        
        texture_sampler_ = SamplerPtr(
            new vk::Sampler(std::move(result.value)),
            SamplerDeleter{*device_}
        );
        
        return {};
    }
    
    VkResult<void> transition_image_layout(
        vk::Image image, vk::Format format,
        vk::ImageLayout old_layout, vk::ImageLayout new_layout)
    {
        vk::CommandBuffer cmd = begin_single_time_commands();
        
        vk::ImageMemoryBarrier barrier{
            .oldLayout = old_layout,
            .newLayout = new_layout,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image,
            .subresourceRange = {
                .aspectMask = vk::ImageAspectFlagBits::eColor,
                .baseMipLevel = 0,
                .levelCount = 1,
                .baseArrayLayer = 0,
                .layerCount = 1
            }
        };
        
        vk::PipelineStageFlags src_stage, dst_stage;
        
        if (old_layout == vk::ImageLayout::eUndefined && 
            new_layout == vk::ImageLayout::eTransferDstOptimal) {
            barrier.srcAccessMask = {};
            barrier.dstAccessMask = vk::AccessFlagBits::eTransferWrite;
            src_stage = vk::PipelineStageFlagBits::eTopOfPipe;
            dst_stage = vk::PipelineStageFlagBits::eTransfer;
        } else if (old_layout == vk::ImageLayout::eTransferDstOptimal &&
                   new_layout == vk::ImageLayout::eShaderReadOnlyOptimal) {
            barrier.srcAccessMask = vk::AccessFlagBits::eTransferWrite;
            barrier.dstAccessMask = vk::AccessFlagBits::eShaderRead;
            src_stage = vk::PipelineStageFlagBits::eTransfer;
            dst_stage = vk::PipelineStageFlagBits::eFragmentShader;
        } else {
            return std::unexpected(VK_ERROR(VkErrorCategory::Rendering,
                "Unsupported layout transition"));
        }
        
        cmd.pipelineBarrier(src_stage, dst_stage, {}, {}, {}, barrier);
        end_single_time_commands(cmd);
        
        return {};
    }
    
    void copy_buffer_to_image(vk::Buffer buffer, vk::Image image, 
                               uint32_t width, uint32_t height) {
        vk::CommandBuffer cmd = begin_single_time_commands();
        
        vk::BufferImageCopy region{
            .bufferOffset = 0,
            .bufferRowLength = 0,
            .bufferImageHeight = 0,
            .imageSubresource = {
                .aspectMask = vk::ImageAspectFlagBits::eColor,
                .mipLevel = 0,
                .baseArrayLayer = 0,
                .layerCount = 1
            },
            .imageOffset = {0, 0, 0},
            .imageExtent = {width, height, 1}
        };
        
        cmd.copyBufferToImage(buffer, image, 
            vk::ImageLayout::eTransferDstOptimal, region);
        
        end_single_time_commands(cmd);
    }
    
    //-------------------------------------------------------------------------
    // Vertex Buffer
    //-------------------------------------------------------------------------
    
    VkResult<void> create_vertex_buffer() {
        constexpr auto vertices = generate_cube_vertices();
        constexpr vk::DeviceSize buffer_size = sizeof(vertices);
        
        // Staging buffer
        BufferPtr staging_buffer;
        DeviceMemoryPtr staging_memory;
        
        VK_TRY(create_buffer(
            buffer_size,
            vk::BufferUsageFlagBits::eTransferSrc,
            vk::MemoryPropertyFlagBits::eHostVisible |
            vk::MemoryPropertyFlagBits::eHostCoherent,
            staging_buffer, staging_memory
        ));
        
        void* data = device_->mapMemory(*staging_memory, 0, buffer_size);
        std::memcpy(data, vertices.data(), buffer_size);
        device_->unmapMemory(*staging_memory);
        
        // Vertex buffer
        VK_TRY(create_buffer(
            buffer_size,
            vk::BufferUsageFlagBits::eTransferDst | vk::BufferUsageFlagBits::eVertexBuffer,
            vk::MemoryPropertyFlagBits::eDeviceLocal,
            vertex_buffer_, vertex_buffer_memory_
        ));
        
        copy_buffer(*staging_buffer, *vertex_buffer_, buffer_size);
        
        return {};
    }
    
    VkResult<void> create_buffer(
        vk::DeviceSize size,
        vk::BufferUsageFlags usage,
        vk::MemoryPropertyFlags properties,
        BufferPtr& buffer, DeviceMemoryPtr& memory)
    {
        vk::BufferCreateInfo buffer_info{
            .size = size,
            .usage = usage,
            .sharingMode = vk::SharingMode::eExclusive
        };
        
        auto result = device_->createBuffer(buffer_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Buffer,
                "Failed to create buffer", result.result));
        }
        
        buffer = BufferPtr(
            new vk::Buffer(std::move(result.value)),
            BufferDeleter{*device_}
        );
        
        auto mem_reqs = device_->getBufferMemoryRequirements(*buffer);
        VK_TRY(allocate_memory(mem_reqs, properties, memory));
        device_->bindBufferMemory(*buffer, *memory, 0);
        
        return {};
    }
    
    void copy_buffer(vk::Buffer src, vk::Buffer dst, vk::DeviceSize size) {
        vk::CommandBuffer cmd = begin_single_time_commands();
        
        vk::BufferCopy copy_region{
            .srcOffset = 0,
            .dstOffset = 0,
            .size = size
        };
        
        cmd.copyBuffer(src, dst, copy_region);
        end_single_time_commands(cmd);
    }
    
    //-------------------------------------------------------------------------
    // Uniform Buffers
    //-------------------------------------------------------------------------
    
    VkResult<void> create_uniform_buffers() {
        constexpr vk::DeviceSize buffer_size = sizeof(UniformBufferObject);
        
        uniform_buffers_.resize(swapchain_images_.size());
        uniform_buffers_memory_.resize(swapchain_images_.size());
        uniform_buffers_mapped_.resize(swapchain_images_.size());
        
        for (size_t i = 0; i < swapchain_images_.size(); ++i) {
            VK_TRY(create_buffer(
                buffer_size,
                vk::BufferUsageFlagBits::eUniformBuffer,
                vk::MemoryPropertyFlagBits::eHostVisible |
                vk::MemoryPropertyFlagBits::eHostCoherent,
                uniform_buffers_[i], uniform_buffers_memory_[i]
            ));
            
            uniform_buffers_mapped_[i] = device_->mapMemory(
                *uniform_buffers_memory_[i], 0, buffer_size);
        }
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Descriptor Pool & Sets
    //-------------------------------------------------------------------------
    
    VkResult<void> create_descriptor_pool() {
        std::array pool_sizes = {
            vk::DescriptorPoolSize{
                .type = vk::DescriptorType::eUniformBuffer,
                .descriptorCount = static_cast<uint32_t>(swapchain_images_.size())
            },
            vk::DescriptorPoolSize{
                .type = vk::DescriptorType::eCombinedImageSampler,
                .descriptorCount = static_cast<uint32_t>(swapchain_images_.size())
            }
        };
        
        vk::DescriptorPoolCreateInfo create_info{
            .maxSets = static_cast<uint32_t>(swapchain_images_.size()),
            .poolSizeCount = static_cast<uint32_t>(pool_sizes.size()),
            .pPoolSizes = pool_sizes.data()
        };
        
        auto result = device_->createDescriptorPool(create_info, nullptr);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Pipeline,
                "Failed to create descriptor pool", result.result));
        }
        
        descriptor_pool_ = DescriptorPoolPtr(
            new vk::DescriptorPool(std::move(result.value)),
            DescriptorPoolDeleter{*device_}
        );
        
        return {};
    }
    
    VkResult<void> create_descriptor_sets() {
        std::vector<vk::DescriptorSetLayout> layouts(
            swapchain_images_.size(), *descriptor_set_layout_);
        
        vk::DescriptorSetAllocateInfo alloc_info{
            .descriptorPool = *descriptor_pool_,
            .descriptorSetCount = static_cast<uint32_t>(layouts.size()),
            .pSetLayouts = layouts.data()
        };
        
        auto result = device_->allocateDescriptorSets(alloc_info);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Pipeline,
                "Failed to allocate descriptor sets", result.result));
        }
        
        descriptor_sets_ = std::move(result.value);
        
        for (size_t i = 0; i < descriptor_sets_.size(); ++i) {
            vk::DescriptorBufferInfo buffer_info{
                .buffer = *uniform_buffers_[i],
                .offset = 0,
                .range = sizeof(UniformBufferObject)
            };
            
            vk::DescriptorImageInfo image_info{
                .sampler = *texture_sampler_,
                .imageView = *texture_image_view_,
                .imageLayout = vk::ImageLayout::eShaderReadOnlyOptimal
            };
            
            std::array descriptor_writes = {
                vk::WriteDescriptorSet{
                    .dstSet = descriptor_sets_[i],
                    .dstBinding = 0,
                    .dstArrayElement = 0,
                    .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eUniformBuffer,
                    .pBufferInfo = &buffer_info,
                },
                vk::WriteDescriptorSet{
                    .dstSet = descriptor_sets_[i],
                    .dstBinding = 1,
                    .dstArrayElement = 0,
                    .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                    .pImageInfo = &image_info,
                }
            };
            
            device_->updateDescriptorSets(descriptor_writes, {});
        }
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Command Buffers
    //-------------------------------------------------------------------------
    
    VkResult<void> create_command_buffers() {
        vk::CommandBufferAllocateInfo alloc_info{
            .commandPool = *command_pool_,
            .level = vk::CommandBufferLevel::ePrimary,
            .commandBufferCount = static_cast<uint32_t>(swapchain_framebuffers_.size())
        };
        
        auto result = device_->allocateCommandBuffers(alloc_info);
        if (result.result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Rendering,
                "Failed to allocate command buffers", result.result));
        }
        
        command_buffers_ = std::move(result.value);
        
        for (size_t i = 0; i < command_buffers_.size(); ++i) {
            vk::CommandBufferBeginInfo begin_info{};
            
            if (command_buffers_[i].begin(&begin_info) != vk::Result::eSuccess) {
                return std::unexpected(VK_ERROR(VkErrorCategory::Rendering,
                    "Failed to begin recording command buffer"));
            }
            
            std::array clear_colors = {
                vk::ClearValue{vk::ClearColorValue{0.1f, 0.1f, 0.15f, 1.0f}},
                vk::ClearValue{vk::ClearDepthStencilValue{1.0f, 0}}
            };
            
            vk::RenderPassBeginInfo render_pass_info{
                .renderPass = *render_pass_,
                .framebuffer = *swapchain_framebuffers_[i],
                .renderArea = {
                    .offset = {0, 0},
                    .extent = swapchain_extent_
                },
                .clearValueCount = static_cast<uint32_t>(clear_colors.size()),
                .pClearValues = clear_colors.data()
            };
            
            command_buffers_[i].beginRenderPass(render_pass_info, 
                vk::SubpassContents::eInline);
            
            command_buffers_[i].bindPipeline(
                vk::PipelineBindPoint::eGraphics, *graphics_pipeline_);
            
            vk::Viewport viewport{
                .x = 0.0f,
                .y = 0.0f,
                .width = static_cast<float>(swapchain_extent_.width),
                .height = static_cast<float>(swapchain_extent_.height),
                .minDepth = 0.0f,
                .maxDepth = 1.0f
            };
            
            vk::Rect2D scissor{
                .offset = {0, 0},
                .extent = swapchain_extent_
            };
            
            command_buffers_[i].setViewport(0, viewport);
            command_buffers_[i].setScissor(0, scissor);
            
            vk::Buffer vertex_buffers[] = {*vertex_buffer_};
            vk::DeviceSize offsets[] = {0};
            command_buffers_[i].bindVertexBuffers(0, vertex_buffers, offsets);
            
            command_buffers_[i].bindDescriptorSets(
                vk::PipelineBindPoint::eGraphics,
                *pipeline_layout_, 0, descriptor_sets_[i], {});
            
            command_buffers_[i].draw(36, 1, 0, 0);
            
            command_buffers_[i].endRenderPass();
            command_buffers_[i].end();
        }
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Sync Objects
    //-------------------------------------------------------------------------
    
    VkResult<void> create_sync_objects() {
        image_available_semaphores_.reserve(max_frames_in_flight);
        render_finished_semaphores_.reserve(max_frames_in_flight);
        in_flight_fences_.reserve(max_frames_in_flight);
        
        for (size_t i = 0; i < max_frames_in_flight; ++i) {
            vk::SemaphoreCreateInfo sem_info{};
            vk::FenceCreateInfo fence_info{
                .flags = vk::FenceCreateFlagBits::eSignaled
            };
            
            auto sem1 = device_->createSemaphore(sem_info, nullptr);
            auto sem2 = device_->createSemaphore(sem_info, nullptr);
            auto fence = device_->createFence(fence_info, nullptr);
            
            if (sem1.result != vk::Result::eSuccess ||
                sem2.result != vk::Result::eSuccess ||
                fence.result != vk::Result::eSuccess) {
                return std::unexpected(VK_ERROR(VkErrorCategory::Synchronization,
                    "Failed to create sync objects"));
            }
            
            image_available_semaphores_.push_back(SemaphorePtr(
                new vk::Semaphore(std::move(sem1.value)),
                SemaphoreDeleter{*device_}
            ));
            
            render_finished_semaphores_.push_back(SemaphorePtr(
                new vk::Semaphore(std::move(sem2.value)),
                SemaphoreDeleter{*device_}
            ));
            
            in_flight_fences_.push_back(FencePtr(
                new vk::Fence(std::move(fence.value)),
                FenceDeleter{*device_}
            ));
        }
        
        images_in_flight_.resize(swapchain_images_.size(), VK_NULL_HANDLE);
        
        return {};
    }
    
    //-------------------------------------------------------------------------
    // Single Time Commands Helper
    //-------------------------------------------------------------------------
    
    vk::CommandBuffer begin_single_time_commands() {
        vk::CommandBufferAllocateInfo alloc_info{
            .commandPool = *command_pool_,
            .level = vk::CommandBufferLevel::ePrimary,
            .commandBufferCount = 1
        };
        
        auto cmd = device_->allocateCommandBuffers(alloc_info).value[0];
        
        vk::CommandBufferBeginInfo begin_info{
            .flags = vk::CommandBufferUsageFlagBits::eOneTimeSubmit
        };
        cmd.begin(begin_info);
        
        return cmd;
    }
    
    void end_single_time_commands(vk::CommandBuffer cmd) {
        cmd.end();
        
        vk::SubmitInfo submit_info{
            .commandBufferCount = 1,
            .pCommandBuffers = &cmd
        };
        
        graphics_queue_.submit(submit_info, vk::Fence{});
        graphics_queue_.waitIdle();
        
        device_->freeCommandBuffers(*command_pool_, cmd);
    }
    
    //-------------------------------------------------------------------------
    // Update & Draw
    //-------------------------------------------------------------------------
    
    void update(const RunningState& state) {
        if (!animation_config_.auto_rotate) return;
        
        rotation_x += animation_config_.rotation_speed_x * state.delta_time;
        rotation_y += animation_config_.rotation_speed_y * state.delta_time;
        rotation_z += animation_config_.rotation_speed_z * state.delta_time;
    }
    
    VkResult<void> draw_frame() {
        auto* running = std::get_if<RunningState>(&state_);
        if (!running) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Rendering, "Not in running state"));
        }
        
        device_->waitForFences(1, &*in_flight_fences_[current_frame_], VK_TRUE, UINT64_MAX);
        
        auto [result, image_index] = device_->acquireNextImageKHR(
            *swapchain_, UINT64_MAX, *image_available_semaphores_[current_frame_], {});
        
        if (result == vk::Result::eErrorOutOfDateKHR) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Swapchain, "Swapchain out of date"));
        }
        if (result != vk::Result::eSuccess && result != vk::Result::eSuboptimalKHR) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Swapchain,
                "Failed to acquire swapchain image", result));
        }
        
        // Update uniform buffer
        update_uniform_buffer(image_index, *running);
        
        // Check if previous frame is using this image
        if (images_in_flight_[image_index]) {
            device_->waitForFences(1, &images_in_flight_[image_index], VK_TRUE, UINT64_MAX);
        }
        images_in_flight_[image_index] = *in_flight_fences_[current_frame_];
        
        // Submit command buffer
        std::array wait_semaphores = {*image_available_semaphores_[current_frame_]};
        std::array signal_semaphores = {*render_finished_semaphores_[current_frame_]};
        vk::PipelineStageFlags wait_stage = vk::PipelineStageFlagBits::eColorAttachmentOutput;
        
        vk::SubmitInfo submit_info{
            .waitSemaphoreCount = 1,
            .pWaitSemaphores = wait_semaphores.data(),
            .pWaitDstStageMask = &wait_stage,
            .commandBufferCount = 1,
            .pCommandBuffers = &command_buffers_[image_index],
            .signalSemaphoreCount = 1,
            .pSignalSemaphores = signal_semaphores.data()
        };
        
        device_->resetFences(1, &*in_flight_fences_[current_frame_]);
        
        if (graphics_queue_.submit(1, &submit_info, *in_flight_fences_[current_frame_]) 
            != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Rendering, "Failed to submit draw"));
        }
        
        // Present
        vk::PresentInfoKHR present_info{
            .waitSemaphoreCount = 1,
            .pWaitSemaphores = signal_semaphores.data(),
            .swapchainCount = 1,
            .pSwapchains = &*swapchain_,
            .pImageIndices = &image_index
        };
        
        auto present_result = present_queue_.presentKHR(present_info);
        
        if (present_result == vk::Result::eErrorOutOfDateKHR || 
            present_result == vk::Result::eSuboptimalKHR) {
            return std::unexpected(VK_ERROR(VkErrorCategory::Swapchain, "Swapchain needs recreation"));
        }
        if (present_result != vk::Result::eSuccess) {
            return std::unexpected(VK_ERROR_RESULT(VkErrorCategory::Swapchain,
                "Failed to present", present_result));
        }
        
        current_frame_ = (current_frame_ + 1) % max_frames_in_flight;
        
        return {};
    }
    
    void update_uniform_buffer(uint32_t current_image, const RunningState& state) {
        UniformBufferObject ubo{};
        
        ubo.model = glm::rotate(glm::mat4(1.0f), deg_to_rad(rotation_x), 
                                glm::vec3(1.0f, 0.0f, 0.0f));
        ubo.model = glm::rotate(ubo.model, deg_to_rad(rotation_y), 
                                glm::vec3(0.0f, 1.0f, 0.0f));
        ubo.model = glm::rotate(ubo.model, deg_to_rad(rotation_z), 
                                glm::vec3(0.0f, 0.0f, 1.0f));
        
        ubo.view = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -3.0f));
        
        float aspect = static_cast<float>(swapchain_extent_.width) / 
                       static_cast<float>(swapchain_extent_.height);
        ubo.proj = glm::perspective(deg_to_rad(45.0f), aspect, 0.1f, 100.0f);
        ubo.proj[1][1] *= -1.0f;  // Vulkan Y-axis is inverted
        
        std::memcpy(uniform_buffers_mapped_[current_image], &ubo, sizeof(ubo));
    }
    
    //-------------------------------------------------------------------------
    // Input Callback
    //-------------------------------------------------------------------------
    
    static void key_callback(GLFWwindow* window, int key, int scancode, 
                             int action, int mods) {
        auto* app = static_cast<VulkanCubeApp*>(glfwGetWindowUserPointer(window));
        if (!app) return;
        
        if (key == GLFW_KEY_ESCAPE && action == GLFW_PRESS) {
            glfwSetWindowShouldClose(window, GLFW_TRUE);
        }
        
        if (key == GLFW_KEY_SPACE && action == GLFW_PRESS) {
            if (std::holds_alternative<RunningState>(app->state_)) {
                app->state_ = PausedState{std::get<RunningState>(app->state_).total_time};
                std::print("Paused\n");
            } else if (std::holds_alternative<PausedState>(app->state_)) {
                app->state_ = RunningState{0.0f, std::get<PausedState>(app->state_).paused_at, 0};
                std::print("Resumed\n");
            }
        }
    }
    
    //-------------------------------------------------------------------------
    // Member Variables
    //-------------------------------------------------------------------------
    
    // Window
    GLFWwindow* window_{nullptr};
    
    // Vulkan core
    vk::Instance instance_;
    vk::PhysicalDevice physical_device_;
    
    // Smart pointer managed resources
    DebugMessengerPtr debug_messenger_;
    SurfacePtr surface_;
    DevicePtr device_;
    SwapchainPtr swapchain_;
    RenderPassPtr render_pass_;
    PipelineLayoutPtr pipeline_layout_;
    PipelinePtr graphics_pipeline_;
    CommandPoolPtr command_pool_;
    
    ShaderModulePtr vertex_shader_module_;
    ShaderModulePtr fragment_shader_module_;
    
    DescriptorSetLayoutPtr descriptor_set_layout_;
    DescriptorPoolPtr descriptor_pool_;
    
    ImagePtr color_image_;
    DeviceMemoryPtr color_image_memory_;
    ImageViewPtr color_image_view_;
    
    ImagePtr depth_image_;
    DeviceMemoryPtr depth_image_memory_;
    ImageViewPtr depth_image_view_;
    
    ImagePtr texture_image_;
    DeviceMemoryPtr texture_image_memory_;
    ImageViewPtr texture_image_view_;
    SamplerPtr texture_sampler_;
    
    BufferPtr vertex_buffer_;
    DeviceMemoryPtr vertex_buffer_memory_;
    
    // Vectors of smart pointers
    std::vector<ImageViewPtr> swapchain_image_views_;
    std::vector<FramebufferPtr> swapchain_framebuffers_;
    std::vector<BufferPtr> uniform_buffers_;
    std::vector<DeviceMemoryPtr> uniform_buffers_memory_;
    
    std::vector<SemaphorePtr> image_available_semaphores_;
    std::vector<SemaphorePtr> render_finished_semaphores_;
    std::vector<FencePtr> in_flight_fences_;
    
    // Raw Vulkan objects (not owned or special lifetime)
    std::vector<vk::Image> swapchain_images_;
    std::vector<vk::CommandBuffer> command_buffers_;
    std::vector<vk::DescriptorSet> descriptor_sets_;
    std::vector<void*> uniform_buffers_mapped_;
    std::vector<vk::Fence> images_in_flight_;
    
    vk::Queue graphics_queue_;
    vk::Queue present_queue_;
    
    // State
    QueueFamilyIndices queue_indices_;
    vk::Format swapchain_image_format_;
    vk::Extent2D swapchain_extent_;
    
    // Animation
    float rotation_x_{0.0f};
    float rotation_y_{0.0f};
    float rotation_z_{0.0f};
    
    // Frame tracking
    static constexpr size_t max_frames_in_flight = 2;
    size_t current_frame_{0};
    
    // Configuration
    static inline constinit WindowConfig window_config_{};
    static inline constinit RenderConfig render_config_{};
    static inline constinit AnimationConfig animation_config_{};
    
    // State machine
    AppState state_{std::monostate{}};
};

//=============================================================================
// Entry Point
//=============================================================================

int main() {
    // Compile-time validations
    constexpr float test = deg_to_rad(90.0f);
    static_assert(test > 1.5f && test < 1.6f, "Degree to radian conversion check");
    
    std::print("Vulkan Spinning Cube - C++23 Features Demo\n");
    std::print("===========================================\n");
    std::print("Controls:\n");
    std::print("  ESC   - Quit\n");
    std::print("  SPACE - Pause/Resume\n\n");
    
    auto app_result = VulkanCubeApp::create();
    
    if (!app_result) {
        std::print(stderr, "Failed to create Vulkan app:\n  {}\n",
                   app_result.error().to_string());
        return 1;
    }
    
    app_result->run();
    
    std::print("\nApplication exited cleanly.\n");
    return 0;
}

// VK_TRY macro for propogating errors
#undef VK_TRY
#define VK_TRY(expr) \
    do { \
        auto _vk_result = (expr); \
        if (!_vk_result.has_value()) { \
            return std::unexpected(std::move(_vk_result.error())); \
        } \
    } while(0)