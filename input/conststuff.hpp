#include <variant>
#include <iostream>
#include <string>

// Represents different types of sensor readings
using SensorData = std::variant<int, double, std::string>;

// 1. CONSTEVAL: Forces compile-time generation of default factory settings
consteval SensorData get_factory_default() {
    return 98.6; // Default temperature as double
}

// 2. CONSTINIT: Global state initialized at compile-time using the consteval function.
// Prevents slow startup code and static init order crashes.
constinit SensorData current_sensor_reading = get_factory_default();

// 3. CONSTEXPR: A function that formats the variant. 
// Works at compile-time (if given compile-time data) or runtime.
constexpr std::string format_reading(const SensorData& data) {
    return std::visit([](auto&& arg) -> std::string {
        using T = std::decay_t<decltype(arg)>;
        if constexpr (std::is_same_v<T, int>) {
            return "Status Code: " + std::to_string(arg);
        } else if constexpr (std::is_same_v<T, double>) {
            return "Temperature: " + std::to_string(arg) + "C";
        } else {
            return "Message: " + arg;
        }
    }, data);
}

int main() {
    // Prove the formatting works at compile time
    constexpr std::string test_format = format_reading(404);
    std::cout << "Compile-time test: " << test_format << "\n";

    // Print the global state (initialized at compile-time via constinit)
    std::cout << "Startup reading: " << format_reading(current_sensor_reading) << "\n";

    // Simulate a runtime sensor update
    current_sensor_reading = std::string("Sensor Offline");
    
    // Print the updated runtime state
    std::cout << "Updated reading: " << format_reading(current_sensor_reading) << "\n";

    return 0;
}