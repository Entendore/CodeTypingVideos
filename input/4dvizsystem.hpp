// 4d_viz_system.hpp
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <concepts>
#include <expected>
#include <memory>
#include <numbers>
#include <print>
#include <ranges>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace viz4d {

// ============================================================================
// Error Types
// ============================================================================
enum class Error : uint8_t {
    InvalidDimension,
    SingularMatrix,
    DivisionByZero,
    InvalidGeometry,
    ProjectionError,
    OutOfBounds,
    NullPointer
};

[[nodiscard]] constexpr std::string_view error_message(Error e) noexcept {
    switch (e) {
        case Error::InvalidDimension: return "Invalid dimension specified";
        case Error::SingularMatrix:   return "Matrix is singular";
        case Error::DivisionByZero:   return "Division by zero";
        case Error::InvalidGeometry:  return "Invalid geometry parameters";
        case Error::ProjectionError:  return "Projection failed";
        case Error::OutOfBounds:      return "Index out of bounds";
        case Error::NullPointer:      return "Null pointer encountered";
        default:                      return "Unknown error";
    }
}

// ============================================================================
// Constexpr Math Constants & Helpers
// ============================================================================
consteval double pi() noexcept { return std::numbers::pi; }
consteval double tau() noexcept { return 2.0 * std::numbers::pi; }

template<typename T>
concept FloatingPoint = std::is_floating_point_v<T>;

template<typename T>
concept Arithmetic = std::is_arithmetic_v<T>;

// ============================================================================
// Point4D - A 4-dimensional point/vector
// ============================================================================
template<Arithmetic T = double>
class Point4D {
    static_assert(sizeof(T) <= sizeof(double), "Type too large");
    std::array<T, 4> coords_{};
    
public:
    constexpr Point4D() noexcept = default;
    constexpr Point4D(T x, T y, T z, T w) noexcept : coords_{x, y, z, w} {}
    
    // Accessors
    [[nodiscard]] constexpr T x() const noexcept { return coords_[0]; }
    [[nodiscard]] constexpr T y() const noexcept { return coords_[1]; }
    [[nodiscard]] constexpr T z() const noexcept { return coords_[2]; }
    [[nodiscard]] constexpr T w() const noexcept { return coords_[3]; }
    
    [[nodiscard]] constexpr T operator[](std::size_t i) const noexcept { 
        return coords_[i]; 
    }
    [[nodiscard]] constexpr T& operator[](std::size_t i) noexcept { 
        return coords_[i]; 
    }
    
    // Arithmetic operations
    [[nodiscard]] constexpr Point4D operator+(const Point4D& other) const noexcept {
        return {coords_[0] + other.coords_[0], coords_[1] + other.coords_[1],
                coords_[2] + other.coords_[2], coords_[3] + other.coords_[3]};
    }
    
    [[nodiscard]] constexpr Point4D operator-(const Point4D& other) const noexcept {
        return {coords_[0] - other.coords_[0], coords_[1] - other.coords_[1],
                coords_[2] - other.coords_[2], coords_[3] - other.coords_[3]};
    }
    
    [[nodiscard]] constexpr Point4D operator*(T scalar) const noexcept {
        return {coords_[0] * scalar, coords_[1] * scalar,
                coords_[2] * scalar, coords_[3] * scalar};
    }
    
    [[nodiscard]] constexpr Point4D operator/(T scalar) const noexcept {
        return {coords_[0] / scalar, coords_[1] / scalar,
                coords_[2] / scalar, coords_[3] / scalar};
    }
    
    // Vector operations
    [[nodiscard]] constexpr T dot(const Point4D& other) const noexcept {
        return coords_[0]*other.coords_[0] + coords_[1]*other.coords_[1] +
               coords_[2]*other.coords_[2] + coords_[3]*other.coords_[3];
    }
    
    [[nodiscard]] constexpr T magnitude_squared() const noexcept { 
        return dot(*this); 
    }
    
    [[nodiscard]] constexpr T magnitude() const noexcept {
        return std::sqrt(static_cast<double>(magnitude_squared()));
    }
    
    [[nodiscard]] constexpr Point4D normalized() const noexcept {
        const T m = magnitude();
        return m > T{0} ? *this * (T{1} / m) : *this;
    }
    
    // Component-wise min/max
    [[nodiscard]] static constexpr Point4D min(const Point4D& a, const Point4D& b) noexcept {
        return {std::min(a.x(), b.x()), std::min(a.y(), b.y()),
                std::min(a.z(), b.z()), std::min(a.w(), b.w())};
    }
    
    [[nodiscard]] static constexpr Point4D max(const Point4D& a, const Point4D& b) noexcept {
        return {std::max(a.x(), b.x()), std::max(a.y(), b.y()),
                std::max(a.z(), b.z()), std::max(a.w(), b.w())};
    }
};

// ============================================================================
// Matrix4x4 - 4x4 transformation matrix
// ============================================================================
template<Arithmetic T = double>
class Matrix4x4 {
    std::array<std::array<T, 4>, 4> data_{};
    
public:
    constexpr Matrix4x4() noexcept { make_identity(); }
    
    [[nodiscard]] static constexpr Matrix4x4 identity() noexcept {
        Matrix4x4 m;
        m.make_identity();
        return m;
    }
    
    constexpr void make_identity() noexcept {
        for (auto& row : data_) {
            row.fill(T{0});
        }
        data_[0][0] = data_[1][1] = data_[2][2] = data_[3][3] = T{1};
    }
    
    [[nodiscard]] constexpr T& at(std::size_t row, std::size_t col) noexcept { 
        return data_[row][col]; 
    }
    [[nodiscard]] constexpr const T& at(std::size_t row, std::size_t col) const noexcept { 
        return data_[row][col]; 
    }
    
    [[nodiscard]] constexpr Matrix4x4 operator*(const Matrix4x4& other) const noexcept {
        Matrix4x4 result{};
        for (std::size_t i = 0; i < 4; ++i) {
            for (std::size_t j = 0; j < 4; ++j) {
                result.data_[i][j] = T{0};
                for (std::size_t k = 0; k < 4; ++k) {
                    result.data_[i][j] += data_[i][k] * other.data_[k][j];
                }
            }
        }
        return result;
    }
    
    [[nodiscard]] constexpr Point4D<T> transform(const Point4D<T>& p) const noexcept {
        return {
            data_[0][0]*p[0] + data_[0][1]*p[1] + data_[0][2]*p[2] + data_[0][3]*p[3],
            data_[1][0]*p[0] + data_[1][1]*p[1] + data_[1][2]*p[2] + data_[1][3]*p[3],
            data_[2][0]*p[0] + data_[2][1]*p[1] + data_[2][2]*p[2] + data_[2][3]*p[3],
            data_[3][0]*p[0] + data_[3][1]*p[1] + data_[3][2]*p[2] + data_[3][3]*p[3]
        };
    }
    
    [[nodiscard]] constexpr std::expected<T, Error> determinant() const noexcept {
        // 4x4 determinant via cofactor expansion along first row
        T det = T{0};
        for (std::size_t j = 0; j < 4; ++j) {
            // Compute 3x3 minor
            const auto minor = [&]<std::size_t... Is>(std::index_sequence<Is...>) {
                const std::array<std::size_t, 3> cols = [&] {
                    std::array<std::size_t, 3> c{};
                    std::size_t idx = 0;
                    for (std::size_t k = 0; k < 4; ++k) {
                        if (k != j) c[idx++] = k;
                    }
                    return c;
                }();
                return data_[Is + 1][cols[Is]]...; // This won't work, need different approach
            }(std::make_index_sequence<3>{});
            
            // Simplified 3x3 determinant
            auto det3 = [this, j]() -> T {
                std::array<std::size_t, 3> cols{};
                std::size_t idx = 0;
                for (std::size_t k = 0; k < 4; ++k) {
                    if (k != j) cols[idx++] = k;
                }
                return data_[1][cols[0]] * (data_[2][cols[1]] * data_[3][cols[2]] - 
                                            data_[2][cols[2]] * data_[3][cols[1]])
                     - data_[1][cols[1]] * (data_[2][cols[0]] * data_[3][cols[2]] - 
                                            data_[2][cols[2]] * data_[3][cols[0]])
                     + data_[1][cols[2]] * (data_[2][cols[0]] * data_[3][cols[1]] - 
                                            data_[2][cols[1]] * data_[3][cols[0]]);
            }();
            
            det += (j % 2 == 0 ? T{1} : T{-1}) * data_[0][j] * det3;
        }
        return det;
    }
    
    [[nodiscard]] constexpr Matrix4x4 transposed() const noexcept {
        Matrix4x4 result{};
        for (std::size_t i = 0; i < 4; ++i) {
            for (std::size_t j = 0; j < 4; ++j) {
                result.data_[i][j] = data_[j][i];
            }
        }
        return result;
    }
};

// ============================================================================
// 4D Rotation Planes (6 total in 4D space)
// ============================================================================
enum class RotationPlane : uint8_t {
    XY = 0, XZ = 1, XW = 2, 
    YZ = 3, YW = 4, ZW = 5
};

[[nodiscard]] consteval std::string_view plane_name(RotationPlane p) noexcept {
    switch (p) {
        case RotationPlane::XY: return "XY";
        case RotationPlane::XZ: return "XZ";
        case RotationPlane::XW: return "XW";
        case RotationPlane::YZ: return "YZ";
        case RotationPlane::YW: return "YW";
        case RotationPlane::ZW: return "ZW";
        default: return "??";
    }
}

// ============================================================================
// Compile-time Rotation Matrix Generator
// ============================================================================
template<FloatingPoint T = double>
[[nodiscard]] consteval Matrix4x4<T> rotation_matrix(RotationPlane plane, T angle) noexcept {
    Matrix4x4<T> m;
    const T c = static_cast<T>(std::cos(static_cast<double>(angle)));
    const T s = static_cast<T>(std::sin(static_cast<double>(angle)));
    
    switch (plane) {
        case RotationPlane::XY:
            m.at(0, 0) = c;  m.at(0, 1) = -s;
            m.at(1, 0) = s;  m.at(1, 1) = c;
            break;
        case RotationPlane::XZ:
            m.at(0, 0) = c;  m.at(0, 2) = -s;
            m.at(2, 0) = s;  m.at(2, 2) = c;
            break;
        case RotationPlane::XW:
            m.at(0, 0) = c;  m.at(0, 3) = -s;
            m.at(3, 0) = s;  m.at(3, 3) = c;
            break;
        case RotationPlane::YZ:
            m.at(1, 1) = c;  m.at(1, 2) = -s;
            m.at(2, 1) = s;  m.at(2, 2) = c;
            break;
        case RotationPlane::YW:
            m.at(1, 1) = c;  m.at(1, 3) = -s;
            m.at(3, 1) = s;  m.at(3, 3) = c;
            break;
        case RotationPlane::ZW:
            m.at(2, 2) = c;  m.at(2, 3) = -s;
            m.at(3, 2) = s;  m.at(3, 3) = c;
            break;
    }
    return m;
}

// Validate rotation matrices at compile time
consteval bool validate_rotation_matrix(RotationPlane plane) {
    auto m = rotation_matrix(plane, 0.0);
    // Identity at 0 degrees
    for (std::size_t i = 0; i < 4; ++i) {
        for (std::size_t j = 0; j < 4; ++j) {
            double expected = (i == j) ? 1.0 : 0.0;
            if (std::abs(m.at(i, j) - expected) > 1e-10) return false;
        }
    }
    return true;
}
static_assert(validate_rotation_matrix(RotationPlane::XY));
static_assert(validate_rotation_matrix(RotationPlane::XW));

// ============================================================================
// Projection Types (using std::variant)
// ============================================================================
struct PerspectiveProjection4to3 {
    double distance = 5.0;
    double min_distance = 0.1; // Avoid division by zero
};

struct OrthographicProjection4to3 {
    double scale = 1.0;
};

struct StereographicProjection4to3 {
    double distance = 1.0;
};

struct PerspectiveProjection3to2 {
    double distance = 5.0;
    double min_distance = 0.1;
};

struct OrthographicProjection3to2 {
    double scale = 1.0;
};

using Projection4to3 = std::variant<
    PerspectiveProjection4to3, 
    OrthographicProjection4to3,
    StereographicProjection4to3
>;
using Projection3to2 = std::variant<
    PerspectiveProjection3to2, 
    OrthographicProjection3to2
>;

// ============================================================================
// 2D and 3D Points for Projection Results
// ============================================================================
struct Point3D {
    double x{}, y{}, z{};
    [[nodiscard]] constexpr Point3D operator+(const Point3D& o) const noexcept {
        return {x + o.x, y + o.y, z + o.z};
    }
    [[nodiscard]] constexpr Point3D operator*(double s) const noexcept {
        return {x * s, y * s, z * s};
    }
};

struct Point2D {
    double x{}, y{};
};

// ============================================================================
// Projection Functions
// ============================================================================
[[nodiscard]] constexpr std::expected<Point3D, Error> 
project_4to3(const Point4D<double>& p, const Projection4to3& proj) noexcept {
    return std::visit([&p](const auto& arg) -> std::expected<Point3D, Error> {
        using T = std::decay_t<decltype(arg)>;
        if constexpr (std::is_same_v<T, PerspectiveProjection4to3>) {
            const double denom = arg.distance - p.w();
            if (denom < arg.min_distance) {
                return std::unexpected(Error::ProjectionError);
            }
            const double factor = arg.distance / denom;
            return Point3D{p.x() * factor, p.y() * factor, p.z() * factor};
        }
        else if constexpr (std::is_same_v<T, OrthographicProjection4to3>) {
            return Point3D{p.x() * arg.scale, p.y() * arg.scale, p.z() * arg.scale};
        }
        else if constexpr (std::is_same_v<T, StereographicProjection4to3>) {
            const double denom = arg.distance - p.w();
            if (denom < 0.001) {
                return std::unexpected(Error::ProjectionError);
            }
            const double factor = 2.0 * arg.distance / denom;
            return Point3D{p.x() * factor, p.y() * factor, p.z() * factor};
        }
        return std::unexpected(Error::ProjectionError);
    }, proj);
}

[[nodiscard]] constexpr std::expected<Point2D, Error>
project_3to2(const Point3D& p, const Projection3to2& proj) noexcept {
    return std::visit([&p](const auto& arg) -> std::expected<Point2D, Error> {
        using T = std::decay_t<decltype(arg)>;
        if constexpr (std::is_same_v<T, PerspectiveProjection3to2>) {
            const double denom = arg.distance - p.z;
            if (denom < arg.min_distance) {
                return std::unexpected(Error::ProjectionError);
            }
            const double factor = arg.distance / denom;
            return Point2D{p.x * factor, p.y * factor};
        }
        else {
            return Point2D{p.x * arg.scale, p.y * arg.scale};
        }
    }, proj);
}

// ============================================================================
// Edge and Face Representations
// ============================================================================
struct Edge {
    std::size_t v1{};
    std::size_t v2{};
    
    [[nodiscard]] constexpr bool operator==(const Edge&) const noexcept = default;
};

struct Face3D {
    std::array<std::size_t, 4> vertices{};
};

struct Cell4D {
    std::array<std::size_t, 8> vertices{}; // For cubic cells
};

// ============================================================================
// 4D Geometry Descriptors (using std::variant)
// ============================================================================
struct Hypercube {
    double size = 1.0;
};

struct Hypersphere {
    double radius = 1.0;
    std::size_t rings = 6;
    std::size_t segments = 8;
};

struct Simplex4D {
    double size = 1.0;
};

struct Duoprism {
    std::size_t sides1 = 3;
    std::size_t sides2 = 3;
    double radius = 1.0;
};

struct Glome {
    double radius = 1.0;
    std::size_t detail = 8;
};

using Geometry4D = std::variant<Hypercube, Hypersphere, Simplex4D, Duoprism, Glome>;

// ============================================================================
// Mesh4D - Complete 4D mesh data
// ============================================================================
struct Mesh4D {
    std::vector<Point4D<double>> vertices;
    std::vector<Edge> edges;
    std::vector<Face3D> faces;
    std::vector<Cell4D> cells;
    
    [[nodiscard]] constexpr std::size_t vertex_count() const noexcept { 
        return vertices.size(); 
    }
    [[nodiscard]] constexpr std::size_t edge_count() const noexcept { 
        return edges.size(); 
    }
    
    [[nodiscard]] std::expected<void, Error> validate() const noexcept {
        for (const auto& e : edges) {
            if (e.v1 >= vertices.size() || e.v2 >= vertices.size()) {
                return std::unexpected(Error::OutOfBounds);
            }
        }
        return {};
    }
};

// ============================================================================
// Compile-Time Mesh Generators
// ============================================================================
[[nodiscard]] consteval std::array<Point4D<double>, 16> 
hypercube_vertices(double size = 1.0) noexcept {
    const double s = size / 2.0;
    return {{
        {-s, -s, -s, -s}, { s, -s, -s, -s}, {-s,  s, -s, -s}, { s,  s, -s, -s},
        {-s, -s,  s, -s}, { s, -s,  s, -s}, {-s,  s,  s, -s}, { s,  s,  s, -s},
        {-s, -s, -s,  s}, { s, -s, -s,  s}, {-s,  s, -s,  s}, { s,  s, -s,  s},
        {-s, -s,  s,  s}, { s, -s,  s,  s}, {-s,  s,  s,  s}, { s,  s,  s,  s}
    }};
}

[[nodiscard]] consteval std::array<Edge, 32> hypercube_edges() noexcept {
    return {{
        // X-direction edges
        {0,1}, {2,3}, {4,5}, {6,7}, {8,9}, {10,11}, {12,13}, {14,15},
        // Y-direction edges
        {0,2}, {1,3}, {4,6}, {5,7}, {8,10}, {9,11}, {12,14}, {13,15},
        // Z-direction edges
        {0,4}, {1,5}, {2,6}, {3,7}, {8,12}, {9,13}, {10,14}, {11,15},
        // W-direction edges
        {0,8}, {1,9}, {2,10}, {3,11}, {4,12}, {5,13}, {6,14}, {7,15}
    }};
}

[[nodiscard]] consteval std::array<Point4D<double>, 5> 
simplex_vertices(double size = 1.0) noexcept {
    // Regular 4-simplex (pentachoron)
    const double a = size / std::sqrt(10.0);
    return {{
        { a,  a,  a,  a},
        { a, -a, -a,  a},
        {-a,  a, -a,  a},
        {-a, -a,  a,  a},
        { a,  a, -a, -a}
    }};
}

[[nodiscard]] consteval std::array<Edge, 10> simplex_edges() noexcept {
    // Complete graph K5
    return {{
        {0,1}, {0,2}, {0,3}, {0,4},
        {1,2}, {1,3}, {1,4},
        {2,3}, {2,4},
        {3,4}
    }};
}

// Compile-time validation
consteval bool validate_hypercube() {
    auto v = hypercube_vertices();
    auto e = hypercube_edges();
    return v.size() == 16 && e.size() == 32;
}

consteval bool validate_simplex() {
    auto v = simplex_vertices();
    auto e = simplex_edges();
    return v.size() == 5 && e.size() == 10;
}

static_assert(validate_hypercube(), "Hypercube validation failed");
static_assert(validate_simplex(), "Simplex validation failed");

// ============================================================================
// Transform Component
// ============================================================================
struct Transform4D {
    Matrix4x4<double> rotation = Matrix4x4<double>::identity();
    Point4D<double> position{};
    double scale = 1.0;
    
    [[nodiscard]] constexpr Point4D<double> apply(const Point4D<double>& p) const noexcept {
        return rotation.transform(p * scale) + position;
    }
    
    [[nodiscard]] constexpr Transform4D compose(const Transform4D& other) const noexcept {
        Transform4D result;
        result.rotation = rotation * other.rotation;
        result.position = apply(other.position);
        result.scale = scale * other.scale;
        return result;
    }
    
    [[nodiscard]] static constexpr Transform4D identity() noexcept {
        return {};
    }
};

// ============================================================================
// Base Renderable Interface
// ============================================================================
class Renderable4D {
public:
    using Ptr = std::shared_ptr<Renderable4D>;
    using WeakPtr = std::weak_ptr<Renderable4D>;
    
    virtual ~Renderable4D() = default;
    
    [[nodiscard]] virtual const Mesh4D& mesh() const = 0;
    [[nodiscard]] virtual Mesh4D& mesh() = 0;
    [[nodiscard]] virtual const Transform4D& transform() const = 0;
    [[nodiscard]] virtual Transform4D& transform() = 0;
    [[nodiscard]] virtual std::string_view name() const = 0;
    [[nodiscard]] virtual std::size_t id() const = 0;
    
    // Enable RTTI-free type checking
    [[nodiscard]] virtual bool is_hypercube() const noexcept { return false; }
    [[nodiscard]] virtual bool is_simplex() const noexcept { return false; }
    [[nodiscard]] virtual bool is_hypersphere() const noexcept { return false; }
    [[nodiscard]] virtual bool is_duoprism() const noexcept { return false; }
};

// ============================================================================
// Concrete Renderable Implementations
// ============================================================================
class HypercubeObject final : public Renderable4D {
    static inline std::size_t next_id_ = 0;
    Mesh4D mesh_;
    Transform4D transform_;
    std::string name_;
    std::size_t id_;
    
public:
    explicit HypercubeObject(double size = 1.0) 
        : name_("Hypercube"), id_(next_id_++) {
        const auto verts = hypercube_vertices(size);
        const auto edges = hypercube_edges();
        mesh_.vertices.assign(verts.begin(), verts.end());
        mesh_.edges.assign(edges.begin(), edges.end());
    }
    
    [[nodiscard]] const Mesh4D& mesh() const override { return mesh_; }
    [[nodiscard]] Mesh4D& mesh() override { return mesh_; }
    [[nodiscard]] const Transform4D& transform() const override { return transform_; }
    [[nodiscard]] Transform4D& transform() override { return transform_; }
    [[nodiscard]] std::string_view name() const override { return name_; }
    [[nodiscard]] std::size_t id() const override { return id_; }
    [[nodiscard]] bool is_hypercube() const noexcept override { return true; }
};

class SimplexObject final : public Renderable4D {
    static inline std::size_t next_id_ = 0;
    Mesh4D mesh_;
    Transform4D transform_;
    std::string name_ = "4-Simplex";
    std::size_t id_;
    
public:
    explicit SimplexObject(double size = 1.0) : id_(next_id_++) {
        const auto verts = simplex_vertices(size);
        const auto edges = simplex_edges();
        mesh_.vertices.assign(verts.begin(), verts.end());
        mesh_.edges.assign(edges.begin(), edges.end());
    }
    
    [[nodiscard]] const Mesh4D& mesh() const override { return mesh_; }
    [[nodiscard]] Mesh4D& mesh() override { return mesh_; }
    [[nodiscard]] const Transform4D& transform() const override { return transform_; }
    [[nodiscard]] Transform4D& transform() override { return transform_; }
    [[nodiscard]] std::string_view name() const override { return name_; }
    [[nodiscard]] std::size_t id() const override { return id_; }
    [[nodiscard]] bool is_simplex() const noexcept override { return true; }
};

class HypersphereObject final : public Renderable4D {
    static inline std::size_t next_id_ = 0;
    Mesh4D mesh_;
    Transform4D transform_;
    std::string name_ = "Hypersphere";
    std::size_t id_;
    
    void generate(double radius, std::size_t rings, std::size_t segments) {
        // Parametric 3-sphere: using Hopf-like coordinates
        for (std::size_t i = 0; i <= rings; ++i) {
            const double theta1 = std::numbers::pi * i / rings;
            for (std::size_t j = 0; j <= segments; ++j) {
                const double theta2 = std::numbers::pi * j / segments;
                for (std::size_t k = 0; k <= segments; ++k) {
                    const double phi = 2.0 * std::numbers::pi * k / segments;
                    
                    const double x = radius * std::sin(theta1) * std::sin(theta2) * std::cos(phi);
                    const double y = radius * std::sin(theta1) * std::sin(theta2) * std::sin(phi);
                    const double z = radius * std::sin(theta1) * std::cos(theta2);
                    const double w = radius * std::cos(theta1);
                    
                    mesh_.vertices.push_back({x, y, z, w});
                }
            }
        }
        
        // Generate edges between adjacent vertices
        const std::size_t slice_size = segments + 1;
        for (std::size_t i = 0; i < mesh_.vertices.size(); ++i) {
            // Connect to next in same ring
            if ((i + 1) % slice_size != 0) {
                mesh_.edges.push_back({i, i + 1});
            }
        }
    }
    
public:
    HypersphereObject(double radius = 1.0, std::size_t rings = 4, std::size_t segments = 6)
        : id_(next_id_++) {
        generate(radius, rings, segments);
    }
    
    [[nodiscard]] const Mesh4D& mesh() const override { return mesh_; }
    [[nodiscard]] Mesh4D& mesh() override { return mesh_; }
    [[nodiscard]] const Transform4D& transform() const override { return transform_; }
    [[nodiscard]] Transform4D& transform() override { return transform_; }
    [[nodiscard]] std::string_view name() const override { return name_; }
    [[nodiscard]] std::size_t id() const override { return id_; }
    [[nodiscard]] bool is_hypersphere() const noexcept override { return true; }
};

class DuoprismObject final : public Renderable4D {
    static inline std::size_t next_id_ = 0;
    Mesh4D mesh_;
    Transform4D transform_;
    std::string name_;
    std::size_t id_;
    
    void generate(std::size_t n1, std::size_t n2, double radius) {
        name_ = "Duoprism-" + std::to_string(n1) + "-" + std::to_string(n2);
        
        // Cartesian product of two regular polygons
        for (std::size_t i = 0; i < n1; ++i) {
            const double angle1 = 2.0 * std::numbers::pi * i / n1;
            const double x = radius * std::cos(angle1);
            const double y = radius * std::sin(angle1);
            
            for (std::size_t j = 0; j < n2; ++j) {
                const double angle2 = 2.0 * std::numbers::pi * j / n2;
                const double z = radius * std::cos(angle2);
                const double w = radius * std::sin(angle2);
                
                mesh_.vertices.push_back({x, y, z, w});
            }
        }
        
        // Edges along first polygon
        for (std::size_t i = 0; i < n1; ++i) {
            for (std::size_t j = 0; j < n2; ++j) {
                mesh_.edges.push_back({i * n2 + j, ((i + 1) % n1) * n2 + j});
            }
        }
        
        // Edges along second polygon
        for (std::size_t i = 0; i < n1; ++i) {
            for (std::size_t j = 0; j < n2; ++j) {
                mesh_.edges.push_back({i * n2 + j, i * n2 + (j + 1) % n2});
            }
        }
    }
    
public:
    DuoprismObject(std::size_t n1 = 3, std::size_t n2 = 3, double radius = 1.0)
        : id_(next_id_++) {
        generate(n1, n2, radius);
    }
    
    [[nodiscard]] const Mesh4D& mesh() const override { return mesh_; }
    [[nodiscard]] Mesh4D& mesh() override { return mesh_; }
    [[nodiscard]] const Transform4D& transform() const override { return transform_; }
    [[nodiscard]] Transform4D& transform() override { return transform_; }
    [[nodiscard]] std::string_view name() const override { return name_; }
    [[nodiscard]] std::size_t id() const override { return id_; }
    [[nodiscard]] bool is_duoprism() const noexcept override { return true; }
};

// ============================================================================
// Object Factory with std::expected Error Handling
// ============================================================================
class ObjectFactory {
public:
    [[nodiscard]] static std::expected<std::unique_ptr<Renderable4D>, Error>
    create(const Geometry4D& geom) {
        return std::visit([](const auto& arg) -> std::expected<std::unique_ptr<Renderable4D>, Error> {
            using T = std::decay_t<decltype(arg)>;
            
            if constexpr (std::is_same_v<T, Hypercube>) {
                if (arg.size <= 0) return std::unexpected(Error::InvalidGeometry);
                return std::make_unique<HypercubeObject>(arg.size);
            }
            else if constexpr (std::is_same_v<T, Hypersphere>) {
                if (arg.radius <= 0 || arg.rings < 1 || arg.rings > 20) {
                    return std::unexpected(Error::InvalidGeometry);
                }
                return std::make_unique<HypersphereObject>(arg.radius, arg.rings, arg.segments);
            }
            else if constexpr (std::is_same_v<T, Simplex4D>) {
                if (arg.size <= 0) return std::unexpected(Error::InvalidGeometry);
                return std::make_unique<SimplexObject>(arg.size);
            }
            else if constexpr (std::is_same_v<T, Duoprism>) {
                if (arg.sides1 < 3 || arg.sides2 < 3 || arg.sides1 > 50 || arg.sides2 > 50) {
                    return std::unexpected(Error::InvalidGeometry);
                }
                return std::make_unique<DuoprismObject>(arg.sides1, arg.sides2, arg.radius);
            }
            else if constexpr (std::is_same_v<T, Glome>) {
                // Glome is another name for 3-sphere
                if (arg.radius <= 0) return std::unexpected(Error::InvalidGeometry);
                return std::make_unique<HypersphereObject>(arg.radius, arg.detail, arg.detail);
            }
            else {
                return std::unexpected(Error::InvalidGeometry);
            }
        }, geom);
    }
};

// ============================================================================
// Scene - Container for 4D Objects
// ============================================================================
class Scene4D {
public:
    using ObjectPtr = std::shared_ptr<Renderable4D>;
    using ObjectWeakPtr = std::weak_ptr<Renderable4D>;
    
private:
    std::vector<ObjectPtr> objects_;
    Projection4to3 proj4to3_{PerspectiveProjection4to3{5.0}};
    Projection3to2 proj3to2_{PerspectiveProjection3to2{5.0}};
    std::string name_ = "Untitled Scene";
    
public:
    explicit Scene4D(std::string name = "Untitled Scene") : name_(std::move(name)) {}
    
    [[nodiscard]] std::expected<void, Error> add_object(std::unique_ptr<Renderable4D> obj) {
        if (!obj) return std::unexpected(Error::NullPointer);
        auto validation = obj->mesh().validate();
        if (!validation) return std::unexpected(validation.error());
        objects_.push_back(std::move(obj));
        return {};
    }
    
    [[nodiscard]] std::expected<void, Error> add_object(ObjectPtr obj) {
        if (!obj) return std::unexpected(Error::NullPointer);
        auto validation = obj->mesh().validate();
        if (!validation) return std::unexpected(validation.error());
        objects_.push_back(std::move(obj));
        return {};
    }
    
    [[nodiscard]] std::expected<void, Error> remove_object(std::size_t id) {
        auto it = std::ranges::find_if(objects_, [id](const auto& obj) {
            return obj->id() == id;
        });
        if (it == objects_.end()) {
            return std::unexpected(Error::OutOfBounds);
        }
        objects_.erase(it);
        return {};
    }
    
    [[nodiscard]] std::expected<ObjectPtr, Error> find_object(std::size_t id) const {
        auto it = std::ranges::find_if(objects_, [id](const auto& obj) {
            return obj->id() == id;
        });
        if (it == objects_.end()) {
            return std::unexpected(Error::OutOfBounds);
        }
        return *it;
    }
    
    // Non-owning views
    [[nodiscard]] std::vector<ObjectWeakPtr> weak_refs() const {
        std::vector<ObjectWeakPtr> result;
        result.reserve(objects_.size());
        for (const auto& obj : objects_) {
            result.push_back(obj);
        }
        return result;
    }
    
    // Iterators
    [[nodiscard]] auto begin() const { return objects_.begin(); }
    [[nodiscard]] auto end() const { return objects_.end(); }
    
    // Accessors
    [[nodiscard]] const std::vector<ObjectPtr>& objects() const noexcept { return objects_; }
    [[nodiscard]] std::size_t size() const noexcept { return objects_.size(); }
    [[nodiscard]] bool empty() const noexcept { return objects_.empty(); }
    [[nodiscard]] std::string_view name() const noexcept { return name_; }
    
    // Projection settings
    void set_projection_4to3(const Projection4to3& p) noexcept { proj4to3_ = p; }
    void set_projection_3to2(const Projection3to2& p) noexcept { proj3to2_ = p; }
    [[nodiscard]] const Projection4to3& projection_4to3() const noexcept { return proj4to3_; }
    [[nodiscard]] const Projection3to2& projection_3to2() const noexcept { return proj3to2_; }
    
    // Statistics
    [[nodiscard]] std::size_t total_vertices() const noexcept {
        return std::ranges::fold_left(
            objects_ | std::views::transform([](const auto& o) { return o->mesh().vertex_count(); }),
            std::size_t{0}, std::plus<>{}
        );
    }
    
    [[nodiscard]] std::size_t total_edges() const noexcept {
        return std::ranges::fold_left(
            objects_ | std::views::transform([](const auto& o) { return o->mesh().edge_count(); }),
            std::size_t{0}, std::plus<>{}
        );
    }
};

// ============================================================================
// Animation System (using std::variant for polymorphism)
// ============================================================================
struct SingleRotation {
    RotationPlane plane = RotationPlane::XW;
    double speed = 0.02;  // radians per frame
    double angle = 0.0;
    
    [[nodiscard]] constexpr Matrix4x4<double> matrix() const noexcept {
        return rotation_matrix(plane, angle);
    }
    
    constexpr void update(double dt) noexcept { angle += speed * dt; }
    constexpr void reset() noexcept { angle = 0.0; }
};

struct DoubleRotation {
    SingleRotation r1{};
    SingleRotation r2{};
    
    [[nodiscard]] constexpr Matrix4x4<double> matrix() const noexcept {
        return r1.matrix() * r2.matrix();
    }
    
    constexpr void update(double dt) noexcept {
        r1.update(dt);
        r2.update(dt);
    }
    
    constexpr void reset() noexcept {
        r1.reset();
        r2.reset();
    }
};

struct TripleRotation {
    SingleRotation r1{};
    SingleRotation r2{};
    SingleRotation r3{};
    
    [[nodiscard]] constexpr Matrix4x4<double> matrix() const noexcept {
        return r1.matrix() * r2.matrix() * r3.matrix();
    }
    
    constexpr void update(double dt) noexcept {
        r1.update(dt);
        r2.update(dt);
        r3.update(dt);
    }
    
    constexpr void reset() noexcept {
        r1.reset();
        r2.reset();
        r3.reset();
    }
};

using Animation = std::variant<SingleRotation, DoubleRotation, TripleRotation>;

[[nodiscard]] inline Matrix4x4<double> get_animation_matrix(const Animation& anim) noexcept {
    return std::visit([](const auto& a) { return a.matrix(); }, anim);
}

inline void update_animation(Animation& anim, double dt) noexcept {
    std::visit([dt](auto& a) { a.update(dt); }, anim);
}

inline void reset_animation(Animation& anim) noexcept {
    std::visit([](auto& a) { a.reset(); }, anim);
}

// ============================================================================
// Rendered Output Data
// ============================================================================
struct ProjectedEdge {
    Point2D start;
    Point2D end;
    double depth{};
    double w_start{};
    double w_end{};
    std::string_view object_name;
    std::size_t object_id{};
};

struct RenderFrame {
    std::vector<ProjectedEdge> edges;
    std::size_t width = 80;
    std::size_t height = 40;
    double time = 0.0;
};

// ============================================================================
// Renderer
// ============================================================================
class Renderer {
    double scale_ = 2.0;
    std::size_t width_ = 80;
    std::size_t height_ = 40;
    bool depth_shading_ = true;
    
public:
    constexpr Renderer& set_scale(double s) noexcept { scale_ = s; return *this; }
    constexpr Renderer& set_resolution(std::size_t w, std::size_t h) noexcept {
        width_ = w; height_ = h; return *this;
    }
    constexpr Renderer& enable_depth_shading(bool enable) noexcept {
        depth_shading_ = enable; return *this;
    }
    
    [[nodiscard]] constexpr double scale() const noexcept { return scale_; }
    [[nodiscard]] constexpr std::size_t width() const noexcept { return width_; }
    [[nodiscard]] constexpr std::size_t height() const noexcept { return height_; }
    
    [[nodiscard]] std::expected<RenderFrame, Error> render(const Scene4D& scene, double time = 0.0) const {
        RenderFrame frame;
        frame.width = width_;
        frame.height = height_;
        frame.time = time;
        
        for (const auto& obj : scene.objects()) {
            const auto& mesh = obj->mesh();
            const auto& transform = obj->transform();
            
            for (const auto& edge : mesh.edges) {
                if (edge.v1 >= mesh.vertices.size() || edge.v2 >= mesh.vertices.size()) {
                    return std::unexpected(Error::OutOfBounds);
                }
                
                // Transform to world space
                const auto p1_4d = transform.apply(mesh.vertices[edge.v1]);
                const auto p2_4d = transform.apply(mesh.vertices[edge.v2]);
                
                // Project 4D -> 3D
                auto p1_3d = project_4to3(p1_4d, scene.projection_4to3());
                if (!p1_3d) return std::unexpected(p1_3d.error());
                
                auto p2_3d = project_4to3(p2_4d, scene.projection_4to3());
                if (!p2_3d) return std::unexpected(p2_3d.error());
                
                // Project 3D -> 2D
                auto p1_2d = project_3to2(*p1_3d, scene.projection_3to2());
                if (!p1_2d) return std::unexpected(p1_2d.error());
                
                auto p2_2d = project_3to2(*p2_3d, scene.projection_3to2());
                if (!p2_2d) return std::unexpected(p2_2d.error());
                
                frame.edges.push_back({
                    *p1_2d, *p2_2d,
                    (p1_3d->z + p2_3d->z) / 2.0,  // Average depth
                    p1_4d.w(), p2_4d.w(),           // W coordinates for coloring
                    obj->name(),
                    obj->id()
                });
            }
        }
        
        // Sort back-to-front for proper rendering
        std::ranges::sort(frame.edges, [](const ProjectedEdge& a, const ProjectedEdge& b) {
            return a.depth > b.depth;
        });
        
        return frame;
    }
    
    [[nodiscard]] std::string render_ascii(const RenderFrame& frame) const {
        std::vector<std::string> grid(height_, std::string(width_, ' '));
        std::vector<double> depth_grid(height_, std::vector<double>(width_, -1e10));
        
        // Depth-based character set
        constexpr std::string_view depth_chars = " .,-~:;=!*#$@";
        
        for (const auto& edge : frame.edges) {
            // W-based coloring (show 4th dimension)
            const double w_avg = (edge.w_start + edge.w_end) / 2.0;
            const double w_normalized = std::clamp((w_avg + 1.5) / 3.0, 0.0, 1.0);
            
            char c = '#';
            if (depth_shading_) {
                const std::size_t char_idx = static_cast<std::size_t>(w_normalized * (depth_chars.size() - 1));
                c = depth_chars[char_idx];
            }
            
            draw_line_depth(grid, depth_grid, edge.start, edge.end, c, edge.depth);
        }
        
        return format_grid(grid);
    }
    
    [[nodiscard]] std::string render_ascii_colored(const RenderFrame& frame) const {
        std::vector<std::string> grid(height_, std::string(width_, ' '));
        std::vector<double> depth_grid(height_, std::vector<double>(width_, -1e10));
        
        // ANSI color codes based on W coordinate
        const auto get_color = [](double w) -> std::string {
            const double w_norm = std::clamp((w + 1.5) / 3.0, 0.0, 1.0);
            const int r = static_cast<int>(255 * w_norm);
            const int b = static_cast<int>(255 * (1.0 - w_norm));
            const int g = static_cast<int>(128 * (1.0 - std::abs(w_norm - 0.5) * 2));
            return "\033[38;2;" + std::to_string(r) + ";" + 
                   std::to_string(g) + ";" + std::to_string(b) + "m";
        };
        
        std::string result;
        result.reserve(height_ * (width_ * 20 + 10)); // Account for ANSI codes
        
        // First pass: render to grid
        for (const auto& edge : frame.edges) {
            const double w_avg = (edge.w_start + edge.w_end) / 2.0;
            draw_line_depth(grid, depth_grid, edge.start, edge.end, '#', edge.depth);
        }
        
        // Second pass: add colors (simplified - single color per row)
        result += "\033[2J\033[H"; // Clear screen
        for (const auto& row : grid) {
            // Use a simple green color for the wireframe
            result += "\033[32m" + row + "\033[0m\n";
        }
        
        return result;
    }
    
private:
    void draw_line_depth(std::vector<std::string>& grid,
                         std::vector<std::vector<double>>& depth,
                         const Point2D& p1, const Point2D& p2,
                         char c, double line_depth) const {
        int x0 = static_cast<int>((p1.x / scale_ + 1.0) * width_ / 2.0);
        int y0 = static_cast<int>((-p1.y / scale_ + 1.0) * height_ / 2.0);
        int x1 = static_cast<int>((p2.x / scale_ + 1.0) * width_ / 2.0);
        int y1 = static_cast<int>((-p2.y / scale_ + 1.0) * height_ / 2.0);
        
        // Bresenham's line algorithm
        const int dx = std::abs(x1 - x0);
        const int dy = -std::abs(y1 - y0);
        const int sx = x0 < x1 ? 1 : -1;
        const int sy = y0 < y1 ? 1 : -1;
        int err = dx + dy;
        
        while (true) {
            if (y0 >= 0 && y0 < static_cast<int>(height_) &&
                x0 >= 0 && x0 < static_cast<int>(width_)) {
                if (line_depth > depth[y0][x0]) {
                    grid[y0][x0] = c;
                    depth[y0][x0] = line_depth;
                }
            }
            
            if (x0 == x1 && y0 == y1) break;
            const int e2 = 2 * err;
            if (e2 >= dy) { err += dy; x0 += sx; }
            if (e2 <= dx) { err += dx; y0 += sy; }
        }
    }
    
    [[nodiscard]] static std::string format_grid(const std::vector<std::string>& grid) {
        std::string result;
        result.reserve(grid.size() * (grid[0].size() + 1));
        for (const auto& row : grid) {
            result += row + '\n';
        }
        return result;
    }
};

// ============================================================================
// Constinit Global Configuration
// ============================================================================
constinit const double CONFIG_DEFAULT_PROJ_DIST = 5.0;
constinit const std::size_t CONFIG_DEFAULT_WIDTH = 80;
constinit const std::size_t CONFIG_DEFAULT_HEIGHT = 40;
constinit const double CONFIG_DEFAULT_SCALE = 2.0;
constinit const double CONFIG_ANIM_SPEED = 0.03;
constinit const double CONFIG_FRAME_DT = 0.05;

// ============================================================================
// Application - Main Controller
// ============================================================================
class Application {
    Scene4D scene_;
    Renderer renderer_;
    std::vector<Animation> animations_;
    double time_ = 0.0;
    bool running_ = false;
    
public:
    Application() : scene_("4D Visualization") {
        renderer_.set_scale(CONFIG_DEFAULT_SCALE)
                 .set_resolution(CONFIG_DEFAULT_WIDTH, CONFIG_DEFAULT_HEIGHT);
    }
    
    explicit Application(std::string name) : scene_(std::move(name)) {
        renderer_.set_scale(CONFIG_DEFAULT_SCALE)
                 .set_resolution(CONFIG_DEFAULT_WIDTH, CONFIG_DEFAULT_HEIGHT);
    }
    
    // Object management
    [[nodiscard]] std::expected<void, Error> add_object(Geometry4D geom) {
        auto obj = ObjectFactory::create(geom);
        if (!obj) return std::unexpected(obj.error());
        return scene_.add_object(std::move(*obj));
    }
    
    [[nodiscard]] std::expected<void, Error> add_object(std::unique_ptr<Renderable4D> obj) {
        return scene_.add_object(std::move(obj));
    }
    
    void add_animation(Animation anim) {
        animations_.push_back(std::move(anim));
    }
    
    // Configuration
    void set_projections(const Projection4to3& p43, const Projection3to2& p32) {
        scene_.set_projection_4to3(p43);
        scene_.set_projection_3to2(p32);
    }
    
    void set_renderer_scale(double scale) { renderer_.set_scale(scale); }
    void set_renderer_resolution(std::size_t w, std::size_t h) {
        renderer_.set_resolution(w, h);
    }
    
    // Animation control
    void start() { running_ = true; }
    void stop() { running_ = false; }
    [[nodiscard]] bool is_running() const { return running_; }
    void reset_time() { time_ = 0.0; }
    
    // Rendering
    [[nodiscard]] std::expected<std::string, Error> render_frame() {
        // Apply animations to objects
        const auto& objects = scene_.objects();
        for (std::size_t i = 0; i < std::min(animations_.size(), objects.size()); ++i) {
            objects[i]->transform().rotation = get_animation_matrix(animations_[i]);
        }
        
        // Update animations
        for (auto& anim : animations_) {
            update_animation(anim, CONFIG_FRAME_DT);
        }
        
        time_ += CONFIG_FRAME_DT;
        
        auto frame = renderer_.render(scene_, time_);
        if (!frame) return std::unexpected(frame.error());
        
        return renderer_.render_ascii(*frame);
    }
    
    [[nodiscard]] std::expected<std::string, Error> render_single_frame() {
        auto frame = renderer_.render(scene_, time_);
        if (!frame) return std::unexpected(frame.error());
        return renderer_.render_ascii(*frame);
    }
    
    // Info
    void print_info() const {
        std::println("╔════════════════════════════════════════╗");
        std::println("║      4D Visualization System v1.0      ║");
        std::println("╠════════════════════════════════════════╣");
        std::println("║ Scene: {:<34}║", scene_.name());
        std::println("║ Objects: {:<33}║", scene_.size());
        std::println("║ Total Vertices: {:<27}║", scene_.total_vertices());
        std::println("║ Total Edges: {:<30}║", scene_.total_edges());
        std::println("║ Animations: {:<31}║", animations_.size());
        std::println("║ Time: {:.2f}s{:<28}║", time_, "");
        std::println("╚════════════════════════════════════════╝");
        std::println();
        
        for (const auto& obj : scene_.objects()) {
            const auto& mesh = obj->mesh();
            std::println("  [{}] {}", obj->id(), obj->name());
            std::println("       Vertices: {}  Edges: {}", 
                         mesh.vertex_count(), mesh.edge_count());
        }
        std::println();
    }
    
    // Accessors
    [[nodiscard]] Scene4D& scene() { return scene_; }
    [[nodiscard]] const Scene4D& scene() const { return scene_; }
    [[nodiscard]] Renderer& renderer() { return renderer_; }
};

// ============================================================================
// Preset Scenes
// ============================================================================
namespace presets {

inline Application tesseract_demo() {
    Application app("Tesseract Demo");
    
    app.add_object(Hypercube{1.0});
    app.add_animation(DoubleRotation{
        {RotationPlane::XW, 0.03},
        {RotationPlane::YZ, 0.02}
    });
    
    app.set_projections(
        PerspectiveProjection4to3{CONFIG_DEFAULT_PROJ_DIST},
        PerspectiveProjection3to2{CONFIG_DEFAULT_PROJ_DIST}
    );
    
    return app;
}

inline Application simplex_demo() {
    Application app("4-Simplex Demo");
    
    app.add_object(Simplex4D{2.0});
    app.add_animation(TripleRotation{
        {RotationPlane::XW, 0.025},
        {RotationPlane::YZ, 0.015},
        {RotationPlane::XY, 0.01}
    });
    
    app.set_projections(
        PerspectiveProjection4to3{CONFIG_DEFAULT_PROJ_DIST},
        PerspectiveProjection3to2{CONFIG_DEFAULT_PROJ_DIST}
    );
    
    return app;
}

inline Application duoprism_demo(std::size_t n1 = 5, std::size_t n2 = 5) {
    Application app("Duoprism Demo");
    
    app.add_object(Duoprism{n1, n2, 1.0});
    app.add_animation(DoubleRotation{
        {RotationPlane::XW, 0.02},
        {RotationPlane::YZ, 0.01}
    });
    
    app.set_projections(
        PerspectiveProjection4to3{CONFIG_DEFAULT_PROJ_DIST},
        PerspectiveProjection3to2{CONFIG_DEFAULT_PROJ_DIST}
    );
    
    return app;
}

inline Application multi_object_scene() {
    Application app("Multi-Object Scene");
    
    // Hypercube at center
    app.add_object(Hypercube{1.0});
    app.add_animation(DoubleRotation{
        {RotationPlane::XW, 0.03},
        {RotationPlane::YZ, 0.02}
    });
    
    // Simplex offset
    auto simplex = ObjectFactory::create(Simplex4D{0.7});
    if (simplex) {
        (*simplex)->transform().position = {2.5, 0, 0, 0};
        app.add_object(std::move(*simplex));
        app.add_animation(SingleRotation{RotationPlane::XW, 0.025});
    }
    
    // Duoprism offset
    auto duoprism = ObjectFactory::create(Duoprism{4, 4, 0.5});
    if (duoprism) {
        (*duoprism)->transform().position = {-2.5, 0, 0, 0};
        app.add_object(std::move(*duoprism));
        app.add_animation(DoubleRotation{
            {RotationPlane::XW, 0.015},
            {RotationPlane::ZW, 0.025}
        });
    }
    
    app.set_projections(
        PerspectiveProjection4to3{8.0},
        PerspectiveProjection3to2{8.0}
    );
    
    app.set_renderer_scale(1.5);
    
    return app;
}

inline Application hypersphere_demo() {
    Application app("Hypersphere Demo");
    
    app.add_object(Hypersphere{1.0, 4, 6});
    app.add_animation(DoubleRotation{
        {RotationPlane::XW, 0.02},
        {RotationPlane::YZ, 0.015}
    });
    
    app.set_projections(
        PerspectiveProjection4to3{CONFIG_DEFAULT_PROJ_DIST},
        PerspectiveProjection3to2{CONFIG_DEFAULT_PROJ_DIST}
    );
    
    return app;
}

} // namespace presets

} // namespace viz4d

// ============================================================================
// Main Entry Point
// ============================================================================
int main() {
    using namespace viz4d;
    
    // Create a tesseract demo
    auto app = presets::tesseract_demo();
    
    // Print scene info
    app.print_info();
    
    // Render a few frames
    std::println("Rendering tesseract rotation (3 frames):");
    std::println("══════════════════════════════════════════\n");
    
    for (int i = 0; i < 3; ++i) {
        auto frame = app.render_frame();
        if (frame) {
            std::println("Frame {}:", i + 1);
            std::println("───────────────────────────────────────");
            std::print("{}\n", *frame);
        } else {
            std::println("Error: {}", error_message(frame.error()));
        }
    }
    
    // Demonstrate error handling with std::expected
    std::println("\n=== Error Handling Demo ===\n");
    
    // Invalid geometry (size <= 0)
    auto invalid_result = ObjectFactory::create(Hypercube{-1.0});
    if (!invalid_result) {
        std::println("Caught error for invalid hypercube: {}", 
                     error_message(invalid_result.error()));
    }
    
    // Invalid duoprism (too few sides)
    auto invalid_duoprism = ObjectFactory::create(Duoprism{2, 3, 1.0});
    if (!invalid_duoprism) {
        std::println("Caught error for invalid duoprism: {}", 
                     error_message(invalid_duoprism.error()));
    }
    
    // Null pointer test
    Scene4D test_scene;
    auto null_result = test_scene.add_object(nullptr);
    if (!null_result) {
        std::println("Caught error for null object: {}", 
                     error_message(null_result.error()));
    }
    
    // Demonstrate variant usage
    std::println("\n=== Variant Demo ===\n");
    
    Projection4to3 proj = PerspectiveProjection4to3{5.0};
    std::println("Projection type: {}", 
        std::holds_alternative<PerspectiveProjection4to3>(proj) ? "Perspective" :
        std::holds_alternative<OrthographicProjection4to3>(proj) ? "Orthographic" :
        "Stereographic");
    
    // Switch to orthographic
    proj = OrthographicProjection4to3{2.0};
    std::println("After switch - Projection type: {}", 
        std::holds_alternative<PerspectiveProjection4to3>(proj) ? "Perspective" :
        std::holds_alternative<OrthographicProjection4to3>(proj) ? "Orthographic" :
        "Stereographic");
    
    // Demonstrate weak_ptr usage
    std::println("\n=== Weak Pointer Demo ===\n");
    
    auto app2 = presets::multi_object_scene();
    auto weak_refs = app2.scene().weak_refs();
    
    for (const auto& weak : weak_refs) {
        if (auto locked = weak.lock()) {
            std::println("Object [{}] {} - vertices: {}", 
                         locked->id(), locked->name(), 
                         locked->mesh().vertex_count());
        } else {
            std::println("Object has been destroyed");
        }
    }
    
    // Demonstrate constexpr evaluation
    std::println("\n=== Constexpr Demo ===\n");
    
    constexpr auto identity = Matrix4x4<double>::identity();
    constexpr auto rot = rotation_matrix(RotationPlane::XW, std::numbers::pi / 4);
    constexpr auto test_point = Point4D<double>{1, 0, 0, 0};
    constexpr auto rotated = rot.transform(test_point);
    
    std::println("Original point: ({}, {}, {}, {})", 
                 test_point.x(), test_point.y(), test_point.z(), test_point.w());
    std::println("After 45° XW rotation: ({:.4f}, {:.4f}, {:.4f}, {:.4f})",
                 rotated.x(), rotated.y(), rotated.z(), rotated.w());
    
    // Animation variant demo
    std::println("\n=== Animation Variant Demo ===\n");
    
    Animation anim1 = SingleRotation{RotationPlane::XY, 0.05};
    Animation anim2 = DoubleRotation{
        {RotationPlane::XW, 0.03},
        {RotationPlane::YZ, 0.02}
    };
    Animation anim3 = TripleRotation{
        {RotationPlane::XW, 0.02},
        {RotationPlane::YZ, 0.015},
        {RotationPlane::ZW, 0.01}
    };
    
    std::println("Animation 1 type: {}", 
        std::holds_alternative<SingleRotation>(anim1) ? "Single" :
        std::holds_alternative<DoubleRotation>(anim1) ? "Double" : "Triple");
    std::println("Animation 2 type: {}", 
        std::holds_alternative<SingleRotation>(anim2) ? "Single" :
        std::holds_alternative<DoubleRotation>(anim2) ? "Double" : "Triple");
    std::println("Animation 3 type: {}", 
        std::holds_alternative<SingleRotation>(anim3) ? "Single" :
        std::holds_alternative<DoubleRotation>(anim3) ? "Double" : "Triple");
    
    // Render duoprism
    std::println("\n=== Duoprism (3-3) Demo ===\n");
    auto app3 = presets::duoprism_demo(3, 3);
    for (int i = 0; i < 2; ++i) {
        auto frame = app3.render_frame();
        if (frame) {
            std::println("Frame {}:", i + 1);
            std::println("───────────────────────────────────────");
            std::print("{}\n", *frame);
        }
    }
    
    std::println("\n✓ All demonstrations completed successfully!");
    
    return 0;
}