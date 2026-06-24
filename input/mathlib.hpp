// example.cpp
#include "game_math.hpp"
#include <iostream>

int main() {
    using namespace math;
    
    // ============================================================================
    // CONSTEVAL - Compile-time computations
    // ============================================================================
    constexpr float rad45 = to_rad(45.0f);  // Computed at compile-time
    constexpr Vec3f forward = Vec3f::forward();
    constexpr Vec3f up = Vec3f::up();
    constexpr Color red = Color::red();
    
    std::cout << "45 degrees in radians: " << rad45 << "\n";
    std::cout << "Forward: " << forward.to_string() << "\n";
    
    // ============================================================================
    // CONSTINIT - Zero-initialized constants
    // ============================================================================
    std::cout << "PI: " << PI << "\n";
    std::cout << "EPSILON: " << EPSILON << "\n";
    
    // ============================================================================
    // CONSTEXPR - Runtime or compile-time
    // ============================================================================
    constexpr Vec3f a{1, 2, 3};
    constexpr Vec3f b{4, 5, 6};
    constexpr float dot = a.dot(b);  // Can be computed at compile-time
    std::cout << "Dot product: " << dot << "\n";
    
    constexpr Vec3f cross = a.cross(b);
    std::cout << "Cross product: " << cross.to_string() << "\n";
    
    // ============================================================================
    // EXPECTED - Error handling for math operations
    // ============================================================================
    Vec3f zero_vec{0, 0, 0};
    auto norm_result = zero_vec.normalized();
    
    if (norm_result) {
        std::cout << "Normalized: " << norm_result->to_string() << "\n";
    } else {
        std::cout << "Cannot normalize zero vector: " << to_string(norm_result.error()) << "\n";
    }
    
    // Matrix inverse with error handling
    Mat4f singular = Mat4f::scaling({0, 1, 1});  // Singular matrix
    auto inv_result = singular.inverse();
    
    if (!inv_result) {
        std::cout << "Matrix inverse failed: " << to_string(inv_result.error()) << "\n";
    }
    
    // Ray-sphere intersection
    Spheref sphere{{0, 0, 5}, 1.0f};
    Rayf ray{{0, 0, 0}, {0, 0, 1}};
    auto hit = sphere.intersect(ray);
    
    if (hit) {
        auto [t1, t2] = *hit;
        std::cout << "Ray hits sphere at t=" << t1 << " and t=" << t2 << "\n";
        std::cout << "Hit point 1: " << ray.point_at(t1).to_string() << "\n";
    }
    
    // ============================================================================
    // VARIANT - Multiple color representations
    // ============================================================================
    Color c1 = Color{1, 0, 0, 1};           // RGBA
    Color c2 = Color{ColorHSV{0, 1, 1}};     // HSV
    Color c3 = Color{0xFF0000FFu};            // HEX
    
    // All convert to RGBA
    std::cout << "Color 1 RGBA: " << c1.r() << ", " << c1.g() << ", " << c1.b() << ", " << c1.a() << "\n";
    std::cout << "Color 2 RGBA: " << c2.r() << ", " << c2.g() << ", " << c2.b() << ", " << c2.a() << "\n";
    std::cout << "Color 3 RGBA: " << c3.r() << ", " << c3.g() << ", " << c3.b() << ", " << c3.a() << "\n";
    
    // Color lerp
    Color blended = Color::red().lerp(Color::blue(), 0.5f);
    std::cout << "Red->Blue blend: " << blended.r() << ", " << blended.g() << ", " << blended.b() << "\n";
    
    // ============================================================================
    // VARIANT - Intersection results
    // ============================================================================
    IntersectionResult result = intersect_ray_sphere(ray, sphere);
    
    std::visit([](auto&& arg) {
        using T = std::decay_t<decltype(arg)>;
        if constexpr (std::is_same_v<T, NoIntersection>) {
            std::cout << "No intersection\n";
        } else if constexpr (std::is_same_v<T, RayIntersection>) {
            std::cout << "Single hit at: " << arg.point.to_string() << "\n";
        } else if constexpr (std::is_same_v<T, TwoPointsIntersection>) {
            std::cout << "Two hits: " << arg.point1.to_string() << " and " << arg.point2.to_string() << "\n";
        }
    }, result);
    
    // ============================================================================
    // SMART POINTERS - Transform hierarchy
    // ============================================================================
    auto root = Transform::create(Vec3f{0, 0, 0});
    auto child1 = Transform::create(Vec3f{2, 0, 0});
    auto child2 = Transform::create(Vec3f{0, 2, 0});
    auto grandchild = Transform::create(Vec3f{0, 0, 2});
    
    root->add_child(child1);
    root->add_child(child2);
    child1->add_child(grandchild);
    
    // Rotation propagates to children
    root->set_rotation(Quatf{Vec3f::up(), to_rad(90.0f)});
    
    std::cout << "Root world pos: " << root->world_position().to_string() << "\n";
    std::cout << "Child1 world pos: " << child1->world_position().to_string() << "\n";
    std::cout << "Grandchild world pos: " << grandchild->world_position().to_string() << "\n";
    
    // ============================================================================
    // SMART POINTERS - Random number generator
    // ============================================================================
    auto rng = Random::create(42);  // Seeded for reproducibility
    
    std::cout << "Random float: " << rng->next_float() << "\n";
    std::cout << "Random int: " << rng->next_int(1, 100) << "\n";
    std::cout << "Random direction: " << rng->next_unit_vector().to_string() << "\n";
    std::cout << "Random color: " << rng->next_color().r() << ", " 
              << rng->next_color().g() << ", " << rng->next_color().b() << "\n";
    
    // ============================================================================
    // SMART POINTERS - Math cache (shared precomputed values)
    // ============================================================================
    auto cache = MathCache::create();
    
    // Get precomputed rotation matrix for 45 degrees
    const Mat4f& rot45 = cache->rotation_y_deg(45.0f);
    std::cout << "Cached rotation matrix:\n" << rot45.to_string();
    
    // ============================================================================
    // QUATERNION OPERATIONS
    // ============================================================================
    Quatf q1 = Quatf::from_euler_yxz(to_rad(45.0f), 0, 0);
    Quatf q2 = Quatf::from_euler_yxz(0, to_rad(90.0f), 0);
    
    // Compose rotations
    Quatf combined = q1 * q2;
    auto euler = combined.to_euler_yxz();
    std::cout << "Combined rotation (euler): " << euler.to_string() << "\n";
    
    // SLERP
    Quatf interpolated = Quatf::slerp(q1, q2, 0.5f);
    std::cout << "SLERP result: " << interpolated.to_string() << "\n";
    
    // Rotate a vector
    Vec3f rotated = q1.rotate(Vec3f{1, 0, 0});
    std::cout << "Rotated vector: " << rotated.to_string() << "\n";
    
    // ============================================================================
    // MATRIX OPERATIONS
    // ============================================================================
    auto view = Mat4f::look_at({0, 5, 10}, {0, 0, 0}, Vec3f::up());
    auto proj = Mat4f::perspective(to_rad(60.0f), 16.0f/9.0f, 0.1f, 100.0f);
    
    if (view && proj) {
        Mat4f vp = *proj * *view;
        auto frustum = Frustumf::from_matrix(vp);
        
        Spheref test_sphere{{0, 0, 0}, 1.0f};
        std::cout << "Sphere visible: " << (frustum.intersects(test_sphere) ? "Yes" : "No") << "\n";
        
        Spheref far_sphere{{0, 0, 200}, 1.0f};
        std::cout << "Far sphere visible: " << (frustum.intersects(far_sphere) ? "Yes" : "No") << "\n";
    }
    
    // ============================================================================
    // EASING with variant
    // ============================================================================
    EasingFunction ease_out = EasingType::EaseOutBounce;
    EasingFunction custom = CustomEasing{[](float t) { return t * t * (3 - 2 * t); }};
    
    for (float t = 0; t <= 1.0f; t += 0.2f) {
        std::cout << "t=" << t << " ease_out=" << Easing::evaluate(ease_out, t) 
                  << " custom=" << Easing::evaluate(custom, t) << "\n";
    }
    
    // ============================================================================
    // BEZIER CURVES
    // ============================================================================
    BezierCurve3f curve{{0, 0, 0}, {1, 2, 0}, {3, 2, 0}, {4, 0, 0}};
    auto points = curve.sample(10);
    std::cout << "Bezier curve points:\n";
    for (const auto& p : points) {
        std::cout << "  " << p.to_string() << "\n";
    }
    
    // ============================================================================
    // AABB OPERATIONS
    // ============================================================================
    AABBf box1{{-1, -1, -1}, {1, 1, 1}};
    AABBf box2{{0, 0, 0}, {2, 2, 2}};
    
    std::cout << "Boxes intersect: " << (box1.intersects(box2) ? "Yes" : "No") << "\n";
    std::cout << "Merged box center: " << box1.merged(box2).center().to_string() << "\n";
    
    // ============================================================================
    // TRIANGLE INTERSECTION
    // ============================================================================
    Triangle tri{{-1, 0, 5}, {1, 0, 5}, {0, 1, 5}};
    auto tri_hit = tri.intersect(ray);
    
    if (tri_hit) {
        std::cout << "Triangle hit at t=" << *tri_hit << "\n";
        std::cout << "Hit point: " << ray.point_at(*tri_hit).to_string() << "\n";
    }
    
    return 0;
}