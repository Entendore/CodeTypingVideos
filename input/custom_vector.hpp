#include <expected>
#include <iostream>
#include <memory>    // For std::uninitialized_move, std::destroy
#include <stdexcept> // For std::out_of_range
#include <utility>   // For std::move, std::forward

template <typename T>
class Vector {
private:
    T* m_data;
    std::size_t m_size;
    std::size_t m_capacity;

    // C++23: Can be constexpr because transient allocations (new/delete) 
    // are now allowed during constant evaluation.
    constexpr void realloc(std::size_t new_capacity) {
        T* new_block = new T[new_capacity];

        // C++17: Move elements into uninitialized memory safely
        std::uninitialized_move(m_data, m_data + m_size, new_block);

        // C++20: Safely call destructors on the old elements
        std::destroy(m_data, m_data + m_size);

        delete[] m_data;
        m_data = new_block;
        m_capacity = new_capacity;
    }

public:
    // -----------------------------------------------------------------------
    // Constructors & Destructor
    // -----------------------------------------------------------------------

    constexpr Vector() : m_data(new T[1]), m_size(0), m_capacity(1) {}

    constexpr Vector(std::size_t count, const T& value) 
        : m_data(new T[count]), m_size(count), m_capacity(count) {
        std::uninitialized_fill_n(m_data, count, value);
    }

    constexpr ~Vector() {
        std::destroy(m_data, m_data + m_size);
        delete[] m_data;
    }

    // -----------------------------------------------------------------------
    // Rule of Five (All marked constexpr)
    // -----------------------------------------------------------------------

    constexpr Vector(const Vector& other) 
        : m_data(new T[other.m_capacity]), m_size(other.m_size), m_capacity(other.m_capacity) {
        std::uninitialized_copy(other.m_data, other.m_data + m_size, m_data);
    }

    constexpr Vector& operator=(const Vector& other) {
        if (this == &other) return *this;

        std::destroy(m_data, m_data + m_size);
        delete[] m_data;

        m_size = other.m_size;
        m_capacity = other.m_capacity;
        m_data = new T[m_capacity];

        std::uninitialized_copy(other.m_data, other.m_data + m_size, m_data);
        return *this;
    }

    constexpr Vector(Vector&& other) noexcept 
        : m_data(other.m_data), m_size(other.m_size), m_capacity(other.m_capacity) {
        other.m_data = nullptr;
        other.m_size = 0;
        other.m_capacity = 0;
    }

    constexpr Vector& operator=(Vector&& other) noexcept {
        if (this == &other) return *this;

        std::destroy(m_data, m_data + m_size);
        delete[] m_data;

        m_data = other.m_data;
        m_size = other.m_size;
        m_capacity = other.m_capacity;

        other.m_data = nullptr;
        other.m_size = 0;
        other.m_capacity = 0;

        return *this;
    }

    // -----------------------------------------------------------------------
    // C++23 Feature: Deducing This (Explicit object parameter)
    // Replaces the need to write both const and non-const overloads!
    // -----------------------------------------------------------------------

    // If called on non-const, returns T&. If called on const, returns const T&.
    template <typename Self>
    constexpr auto&& operator[](this Self&& self, std::size_t index) {
        return std::forward<Self>(self).m_data[index];
    }

    template <typename Self>
    constexpr auto&& front(this Self&& self) {
        return std::forward<Self>(self).m_data[0];
    }

    template <typename Self>
    constexpr auto&& back(this Self&& self) {
        return std::forward<Self>(self).m_data[self.m_size - 1];
    }

    // -----------------------------------------------------------------------
    // C++23 Feature: std::expected for Error Handling
    // C++23 allows std::expected to hold references (std::expected<T&, E>)
    // -----------------------------------------------------------------------
    
    template <typename Self>
    constexpr auto at(this Self&& self, std::size_t index) 
        -> std::expected<decltype(std::forward<Self>(self).m_data[0]), std::out_of_range> 
    {
        if (index >= self.m_size) {
            return std::unexpected(std::out_of_range("Vector index out of bounds"));
        }
        return std::forward<Self>(self).m_data[index];
    }

    // -----------------------------------------------------------------------
    // Modifiers
    // -----------------------------------------------------------------------

    constexpr void push_back(const T& value) {
        if (m_size >= m_capacity) {
            realloc(m_capacity == 0 ? 1 : m_capacity * 2);
        }
        m_data[m_size++] = value;
    }

    constexpr void push_back(T&& value) {
        if (m_size >= m_capacity) {
            realloc(m_capacity == 0 ? 1 : m_capacity * 2);
        }
        m_data[m_size++] = std::move(value);
    }

    constexpr void pop_back() {
        if (m_size > 0) {
            // C++20: Destroy the element in place rather than manually calling ~T()
            std::destroy_at(m_data + --m_size);
        }
    }

    constexpr void clear() {
        // C++20: Destroy a range of elements
        std::destroy(m_data, m_data + m_size);
        m_size = 0;
    }

    // -----------------------------------------------------------------------
    // Iterators (Required to work with C++20/C++23 Ranges)
    // -----------------------------------------------------------------------

    constexpr T* begin() { return m_data; }
    constexpr T* end() { return m_data + m_size; }
    constexpr const T* begin() const { return m_data; }
    constexpr const T* end() const { return m_data + m_size; }

    // -----------------------------------------------------------------------
    // Capacity & Size
    // -----------------------------------------------------------------------

    constexpr std::size_t size() const { return m_size; }
    constexpr std::size_t capacity() const { return m_capacity; }
    constexpr bool empty() const { return m_size == 0; }
};

// -----------------------------------------------------------------------
// Demonstration
// -----------------------------------------------------------------------
int main() {
    // 1. Compile-time evaluation (C++23 feature: constexpr new/delete)
    constexpr auto create_vector = [] {
        Vector<int> v;
        v.push_back(10);
        v.push_back(20);
        return v;
    };
    constexpr Vector<int> const_vec = create_vector();
    std::cout << "Compile-time vector size: " << const_vec.size() << "\n";

    // 2. Runtime vector
    Vector<std::string> names;
    names.push_back("Alice");
    names.push_back("Bob");

    std::string temp = "Charlie";
    names.push_back(std::move(temp));

    // 3. C++23 Ranges integration (because we provided begin()/end())
    std::cout << "Names: ";
    for (const auto& name : names) {
        std::cout << name << " ";
    }
    std::cout << "\n";

    // 4. Deducing `this` in action (works seamlessly with const)
    const auto& const_names = names;
    std::cout << "Const access via deducing this: " << const_names.front() << "\n";

    // 5. C++23 std::expected error handling
    std::cout << "\nTesting std::expected for bounds checking:\n";
    
    auto result1 = names.at(1);
    if (result1) {
        std::cout << "Index 1 is valid: " << result1.value() << "\n";
    }

    auto result2 = names.at(99);
    if (!result2) {
        std::cout << "Index 99 failed. Error: " << result2.error().what() << "\n";
    }

    return 0;
}