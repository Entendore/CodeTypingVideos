#include <cstdint>
#include <memory>
#include <variant>
#include <expected>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <type_traits>
#include <concepts>
#include <string>
#include <string_view>
#include <functional>
#include <algorithm>
#include <print>
#include <array>
#include <source_location>

namespace ecs {

// ============================================================================
// ERROR HANDLING
// ============================================================================

enum class Error : uint8_t {
    EntityNotFound,
    ComponentNotFound,
    EntityAlreadyExists,
    ComponentAlreadyExists,
    InvalidEntityId,
    OutOfCapacity,
};

[[nodiscard]] constexpr std::string_view error_to_string(Error e) noexcept {
    switch (e) {
        case Error::EntityNotFound:       return "Entity not found";
        case Error::ComponentNotFound:    return "Component not found";
        case Error::EntityAlreadyExists:  return "Entity already exists";
        case Error::ComponentAlreadyExists: return "Component already exists";
        case Error::InvalidEntityId:      return "Invalid entity ID";
        case Error::OutOfCapacity:        return "Out of capacity";
        default:                          return "Unknown error";
    }
}

// ============================================================================
// ENTITY ID
// ============================================================================

using EntityId = uint32_t;

// Compile-time constants
constinit const EntityId INVALID_ENTITY_ID = 0;
constinit const size_t MAX_ENTITIES = 1'000'000;

// Compile-time validation
consteval void validate_entity_id(EntityId id) {
    if (id == INVALID_ENTITY_ID) {
        throw "Invalid entity ID";
    }
}

[[nodiscard]] consteval bool is_valid_entity_id(EntityId id) noexcept {
    return id != INVALID_ENTITY_ID;
}

// ============================================================================
// COMPONENTS
// ============================================================================

struct Position {
    float x{};
    float y{};
    float z{};

    consteval Position() noexcept = default;
    consteval Position(float x, float y, float z) noexcept : x{x}, y{y}, z{z} {}

    [[nodiscard]] consteval bool is_zero() const noexcept {
        return x == 0.0f && y == 0.0f && z == 0.0f;
    }
};

struct Velocity {
    float dx{};
    float dy{};
    float dz{};

    consteval Velocity() noexcept = default;
    consteval Velocity(float dx, float dy, float dz) noexcept : dx{dx}, dy{dy}, dz{dz} {}

    [[nodiscard]] consteval float magnitude_squared() const noexcept {
        return dx * dx + dy * dy + dz * dz;
    }

    [[nodiscard]] consteval bool is_zero() const noexcept {
        return dx == 0.0f && dy == 0.0f && dz == 0.0f;
    }
};

struct Health {
    int value{100};
    int max{100};

    consteval Health() noexcept = default;
    consteval Health(int v, int m) noexcept : value{v}, max{m} {}

    [[nodiscard]] consteval bool is_dead() const noexcept { return value <= 0; }
    [[nodiscard]] consteval bool is_full() const noexcept { return value >= max; }
    [[nodiscard]] consteval float percentage() const noexcept {
        return max > 0 ? static_cast<float>(value) / static_cast<float>(max) : 0.0f;
    }
};

struct Renderable {
    uint32_t textureId{};
    float scale{1.0f};
    bool visible{true};

    consteval Renderable() noexcept = default;
    consteval Renderable(uint32_t id, float s = 1.0f, bool v = true) noexcept
        : textureId{id}, scale{s}, visible{v} {}
};

struct Name {
    std::string value{};

    Name() = default;
    Name(std::string name) : value{std::move(name)} {}

    [[nodiscard]] bool empty() const noexcept { return value.empty(); }
};

struct Tag {
    std::string value{};

    Tag() = default;
    Tag(std::string tag) : value{std::move(tag)} {}
};

// Component variant - monostate for optional/empty state
using ComponentVariant = std::variant<
    std::monostate,
    Position,
    Velocity,
    Health,
    Renderable,
    Name,
    Tag
>;

// ============================================================================
// COMPONENT TRAITS
// ============================================================================

// Concept for valid components
template<typename T>
concept Component = std::is_same_v<std::remove_cvref_t<T>, Position>  ||
                    std::is_same_v<std::remove_cvref_t<T>, Velocity>  ||
                    std::is_same_v<std::remove_cvref_t<T>, Health>    ||
                    std::is_same_v<std::remove_cvref_t<T>, Renderable>||
                    std::is_same_v<std::remove_cvref_t<T>, Name>      ||
                    std::is_same_v<std::remove_cvref_t<T>, Tag>;

// Compile-time component type index (C++23 variant::index_of)
template<Component T>
consteval size_t component_index() noexcept {
    return ComponentVariant::index_of<std::remove_cvref_t<T>>;
}

// Compile-time component count (excluding monostate)
consteval size_t component_count() noexcept {
    return std::variant_size_v<ComponentVariant> - 1;
}

// Compile-time component name
template<Component T>
consteval std::string_view component_name() noexcept {
    if constexpr (std::is_same_v<T, Position>)   return "Position";
    if constexpr (std::is_same_v<T, Velocity>)   return "Velocity";
    if constexpr (std::is_same_v<T, Health>)     return "Health";
    if constexpr (std::is_same_v<T, Renderable>) return "Renderable";
    if constexpr (std::is_same_v<T, Name>)       return "Name";
    if constexpr (std::is_same_v<T, Tag>)        return "Tag";
    return "Unknown";
}

// ============================================================================
// COMPONENT POOL
// ============================================================================

class ComponentPool {
public:
    using Storage = std::unordered_map<EntityId, ComponentVariant>;

    ComponentPool() = default;
    
    // Non-copyable, movable
    ComponentPool(const ComponentPool&) = delete;
    ComponentPool& operator=(const ComponentPool&) = delete;
    ComponentPool(ComponentPool&&) noexcept = default;
    ComponentPool& operator=(ComponentPool&&) noexcept = default;

    // Add component to entity
    template<Component T>
    void add(EntityId id, T&& component) {
        storage_[id] = std::forward<T>(component);
    }

    // Get component from entity
    template<Component T>
    [[nodiscard]] std::expected<std::reference_wrapper<T>, Error> get(EntityId id) {
        auto it = storage_.find(id);
        if (it == storage_.end()) {
            return std::unexpected(Error::ComponentNotFound);
        }
        if (auto* ptr = std::get_if<T>(&it->second)) {
            return std::ref(*ptr);
        }
        return std::unexpected(Error::ComponentNotFound);
    }

    // Get component from entity (const version)
    template<Component T>
    [[nodiscard]] std::expected<std::reference_wrapper<const T>, Error> get(EntityId id) const {
        auto it = storage_.find(id);
        if (it == storage_.end()) {
            return std::unexpected(Error::ComponentNotFound);
        }
        if (auto* ptr = std::get_if<T>(&it->second)) {
            return std::cref(*ptr);
        }
        return std::unexpected(Error::ComponentNotFound);
    }

    // Remove component from entity
    [[nodiscard]] std::expected<void, Error> remove(EntityId id) {
        auto it = storage_.find(id);
        if (it == storage_.end()) {
            return std::unexpected(Error::ComponentNotFound);
        }
        storage_.erase(it);
        return {};
    }

    // Check if entity has specific component type
    template<Component T>
    [[nodiscard]] bool has(EntityId id) const {
        auto it = storage_.find(id);
        if (it == storage_.end()) return false;
        return std::holds_alternative<T>(it->second);
    }

    // Check if entity has any component in this pool
    [[nodiscard]] bool contains(EntityId id) const {
        return storage_.contains(id);
    }

    // Get all entity IDs with components in this pool
    [[nodiscard]] const Storage& get_storage() const noexcept { return storage_; }

    // Get all entity IDs
    [[nodiscard]] std::vector<EntityId> get_entity_ids() const {
        std::vector<EntityId> ids;
        ids.reserve(storage_.size());
        for (const auto& [id, _] : storage_) {
            ids.push_back(id);
        }
        return ids;
    }

    // Clear all components
    void clear() noexcept { storage_.clear(); }

    // Size
    [[nodiscard]] size_t size() const noexcept { return storage_.size(); }

    // Check if empty
    [[nodiscard]] bool empty() const noexcept { return storage_.empty(); }

private:
    Storage storage_;
};

// ============================================================================
// ENTITY MANAGER
// ============================================================================

class EntityManager {
public:
    EntityManager() {
        freeIds_.reserve(256);
        entities_.reserve(256);
    }

    // Non-copyable
    EntityManager(const EntityManager&) = delete;
    EntityManager& operator=(const EntityManager&) = delete;
    EntityManager(EntityManager&&) = default;
    EntityManager& operator=(EntityManager&&) = default;

    [[nodiscard]] std::expected<EntityId, Error> create() {
        if (nextId_ >= MAX_ENTITIES && freeIds_.empty()) {
            return std::unexpected(Error::OutOfCapacity);
        }

        EntityId id;
        if (!freeIds_.empty()) {
            id = freeIds_.back();
            freeIds_.pop_back();
        } else {
            id = nextId_++;
        }

        entities_.insert(id);
        return id;
    }

    [[nodiscard]] std::expected<void, Error> destroy(EntityId id) {
        if (!entities_.contains(id)) {
            return std::unexpected(Error::EntityNotFound);
        }
        entities_.erase(id);
        freeIds_.push_back(id);
        return {};
    }

    [[nodiscard]] bool exists(EntityId id) const noexcept {
        return entities_.contains(id);
    }

    [[nodiscard]] size_t count() const noexcept {
        return entities_.size();
    }

    [[nodiscard]] const std::unordered_set<EntityId>& all() const noexcept {
        return entities_;
    }

    void clear() noexcept {
        entities_.clear();
        freeIds_.clear();
        nextId_ = 1;
    }

    [[nodiscard]] size_t capacity() const noexcept {
        return MAX_ENTITIES;
    }

private:
    std::unordered_set<EntityId> entities_;
    std::vector<EntityId> freeIds_;
    EntityId nextId_{1}; // 0 is invalid
};

// ============================================================================
// WORLD (Main ECS Registry)
// ============================================================================

class World {
public:
    World() = default;
    
    World(const World&) = delete;
    World& operator=(const World&) = delete;
    World(World&&) = default;
    World& operator=(World&&) = default;

    // ==================== Entity Operations ====================

    [[nodiscard]] std::expected<EntityId, Error> create_entity() {
        return entityManager_.create();
    }

    [[nodiscard]] std::expected<void, Error> destroy_entity(EntityId id) {
        auto result = entityManager_.destroy(id);
        if (!result) return result;

        // Remove all components for this entity
        for (auto& pool : componentPools_) {
            if (pool) {
                pool->remove(id);
            }
        }

        return {};
    }

    [[nodiscard]] bool entity_exists(EntityId id) const noexcept {
        return entityManager_.exists(id);
    }

    [[nodiscard]] size_t entity_count() const noexcept {
        return entityManager_.count();
    }

    // ==================== Component Operations ====================

    template<Component T>
    [[nodiscard]] std::expected<void, Error> add_component(EntityId id, T component) {
        if (!entityManager_.exists(id)) {
            return std::unexpected(Error::EntityNotFound);
        }

        auto& pool = get_pool<T>();
        if (pool.has<T>(id)) {
            return std::unexpected(Error::ComponentAlreadyExists);
        }

        pool.add(id, std::move(component));
        return {};
    }

    template<Component T>
    [[nodiscard]] std::expected<std::reference_wrapper<T>, Error> get_component(EntityId id) {
        if (!entityManager_.exists(id)) {
            return std::unexpected(Error::EntityNotFound);
        }
        return get_pool<T>().get<T>(id);
    }

    template<Component T>
    [[nodiscard]] std::expected<std::reference_wrapper<const T>, Error> get_component(EntityId id) const {
        if (!entityManager_.exists(id)) {
            return std::unexpected(Error::EntityNotFound);
        }
        return get_pool<T>().get<T>(id);
    }

    template<Component T>
    [[nodiscard]] std::expected<void, Error> remove_component(EntityId id) {
        if (!entityManager_.exists(id)) {
            return std::unexpected(Error::EntityNotFound);
        }
        return get_pool<T>().remove(id);
    }

    template<Component T>
    [[nodiscard]] bool has_component(EntityId id) const {
        return get_pool<T>().has<T>(id);
    }

    // ==================== Query Operations ====================

    // Query entities with ALL specified components
    template<Component... Ts>
    [[nodiscard]] std::vector<EntityId> query() const {
        std::vector<EntityId> result;

        for (EntityId id : entityManager_.all()) {
            if ((has_component<Ts>(id) && ...)) {
                result.push_back(id);
            }
        }

        return result;
    }

    // Query with callback (non-const components)
    template<Component... Ts, typename Func>
    void each(Func&& func) {
        for (EntityId id : entityManager_.all()) {
            if ((has_component<Ts>(id) && ...)) {
                // Unpack all component references
                func(id, get_component<Ts>(id).value().get()...);
            }
        }
    }

    // Query with callback (const components)
    template<Component... Ts, typename Func>
    void each(Func&& func) const {
        for (EntityId id : entityManager_.all()) {
            if ((has_component<Ts>(id) && ...)) {
                func(id, get_component<Ts>(id).value().get()...);
            }
        }
    }

    // Query entities with ANY of the specified components
    template<Component... Ts>
    [[nodiscard]] std::vector<EntityId> query_any() const {
        std::vector<EntityId> result;
        std::unordered_set<EntityId> seen;

        auto check_and_add = [&](EntityId id) {
            if (!seen.contains(id)) {
                seen.insert(id);
                result.push_back(id);
            }
        };

        ((for (EntityId id : get_pool<Ts>().get_entity_ids()) { 
            check_and_add(id); 
        }), ...);

        return result;
    }

    // ==================== Utility Operations ====================

    void clear() {
        for (auto& pool : componentPools_) {
            if (pool) {
                pool->clear();
            }
        }
        entityManager_.clear();
    }

    // Get component count for specific type
    template<Component T>
    [[nodiscard]] size_t component_count() const noexcept {
        constexpr size_t idx = component_index<T>();
        return componentPools_[idx] ? componentPools_[idx]->size() : 0;
    }

    // Get entity manager (for advanced use)
    [[nodiscard]] const EntityManager& entity_manager() const noexcept {
        return entityManager_;
    }

private:
    template<Component T>
    ComponentPool& get_pool() {
        constexpr size_t idx = component_index<T>();
        if (!componentPools_[idx]) {
            componentPools_[idx] = std::make_unique<ComponentPool>();
        }
        return *componentPools_[idx];
    }

    template<Component T>
    const ComponentPool& get_pool() const {
        constexpr size_t idx = component_index<T>();
        static ComponentPool empty_pool;
        return componentPools_[idx] ? *componentPools_[idx] : empty_pool;
    }

    EntityManager entityManager_;
    std::array<std::unique_ptr<ComponentPool>, std::variant_size_v<ComponentVariant>> componentPools_{};
};

// ============================================================================
// SYSTEM BASE CLASS (CRTP)
// ============================================================================

template<typename Derived>
class System {
public:
    explicit System(World& world) noexcept : world_{world} {}

    System(const System&) = delete;
    System& operator=(const System&) = delete;
    
    virtual ~System() = default;

    [[nodiscard]] World& get_world() noexcept { return world_; }
    [[nodiscard]] const World& get_world() const noexcept { return world_; }

protected:
    World& world_;
};

// ============================================================================
// CONCRETE SYSTEMS
// ============================================================================

// Movement System - Updates positions based on velocities
class MovementSystem : public System<MovementSystem> {
public:
    using System::System;

    void update(float dt) {
        world_.each<Position, Velocity>([dt](EntityId id, Position& pos, Velocity& vel) {
            pos.x += vel.dx * dt;
            pos.y += vel.dy * dt;
            pos.z += vel.dz * dt;
            
            // Optional: Log very fast moving entities
            if (vel.magnitude_squared() > 100.0f) {
                std::println("Entity {} moving fast!", id);
            }
        });
    }
};

// Health System - Manages health, damage, healing
class HealthSystem : public System<HealthSystem> {
public:
    using System::System;

    void damage(EntityId id, int amount) {
        if (auto health = world_.get_component<Health>(id)) {
            health->get().value = std::max(0, health->get().value - amount);
        }
    }

    void heal(EntityId id, int amount) {
        if (auto health = world_.get_component<Health>(id)) {
            auto& h = health->get();
            h.value = std::min(h.max, h.value + amount);
        }
    }

    void kill(EntityId id) {
        if (auto health = world_.get_component<Health>(id)) {
            health->get().value = 0;
        }
    }

    void revive(EntityId id, int health = 100) {
        if (auto h = world_.get_component<Health>(id)) {
            h->get().value = std::min(health, h->get().max);
        }
    }

    [[nodiscard]] std::vector<EntityId> get_dead_entities() const {
        std::vector<EntityId> dead;
        world_.each<Health>([&dead](EntityId id, const Health& h) {
            if (h.is_dead()) {
                dead.push_back(id);
            }
        });
        return dead;
    }

    [[nodiscard]] std::vector<EntityId> get_alive_entities() const {
        std::vector<EntityId> alive;
        world_.each<Health>([&alive](EntityId id, const Health& h) {
            if (!h.is_dead()) {
                alive.push_back(id);
            }
        });
        return alive;
    }
};

// Render System - Handles visibility and rendering
class RenderSystem : public System<RenderSystem> {
public:
    using System::System;

    void update() {
        world_.each<Renderable, Position>([](EntityId id, Renderable& r, const Position& p) {
            if (r.visible && r.scale > 0.0f) {
                // In a real engine, this would queue for rendering
                std::println("  Rendering entity {} at ({:.1f}, {:.1f}, {:.1f}) tex:{} scale:{:.1f}",
                    id, p.x, p.y, p.z, r.textureId, r.scale);
            }
        });
    }

    void set_visible(EntityId id, bool visible) {
        if (auto r = world_.get_component<Renderable>(id)) {
            r->get().visible = visible;
        }
    }

    void set_scale(EntityId id, float scale) {
        if (auto r = world_.get_component<Renderable>(id)) {
            r->get().scale = std::max(0.0f, scale);
        }
    }
};

// Debug/System Info System
class DebugSystem : public System<DebugSystem> {
public:
    using System::System;

    void print_entity_info(EntityId id) const {
        if (!world_.entity_exists(id)) {
            std::println("Entity {} does not exist", id);
            return;
        }

        std::println("Entity {}:", id);
        
        if (auto pos = world_.get_component<Position>(id)) {
            std::println("  Position: ({:.1f}, {:.1f}, {:.1f})", 
                pos->get().x, pos->get().y, pos->get().z);
        }
        if (auto vel = world_.get_component<Velocity>(id)) {
            std::println("  Velocity: ({:.1f}, {:.1f}, {:.1f})",
                vel->get().dx, vel->get().dy, vel->get().dz);
        }
        if (auto health = world_.get_component<Health>(id)) {
            std::println("  Health: {}/{} ({:.0f}%)",
                health->get().value, health->get().max, health->get().percentage() * 100);
        }
        if (auto renderable = world_.get_component<Renderable>(id)) {
            std::println("  Renderable: tex={} scale={:.1f} visible={}",
                renderable->get().textureId, renderable->get().scale, renderable->get().visible);
        }
        if (auto name = world_.get_component<Name>(id)) {
            std::println("  Name: \"{}\"", name->get().value);
        }
        if (auto tag = world_.get_component<Tag>(id)) {
            std::println("  Tag: \"{}\"", tag->get().value);
        }
    }

    void print_stats() const {
        std::println("=== World Stats ===");
        std::println("Entities: {}", world_.entity_count());
        std::println("Components:");
        std::println("  Position:   {}", world_.component_count<Position>());
        std::println("  Velocity:   {}", world_.component_count<Velocity>());
        std::println("  Health:     {}", world_.component_count<Health>());
        std::println("  Renderable: {}", world_.component_count<Renderable>());
        std::println("  Name:       {}", world_.component_count<Name>());
        std::println("  Tag:        {}", world_.component_count<Tag>());
        std::println("===================");
    }
};

// ============================================================================
// ENTITY BUILDER (Fluent API)
// ============================================================================

class EntityBuilder {
public:
    explicit EntityBuilder(World& world) : world_{world} {}

    EntityBuilder(const EntityBuilder&) = delete;
    EntityBuilder& operator=(const EntityBuilder&) = delete;

    template<Component T>
    EntityBuilder& with(T component) {
        pendingComponents_.push_back(
            [c = std::move(component)](World& w, EntityId id) mutable {
                w.add_component(id, std::move(c));
            }
        );
        return *this;
    }

    [[nodiscard]] std::expected<EntityId, Error> build() {
        auto entity = world_.create_entity();
        if (!entity) return entity;

        EntityId id = entity.value();

        for (auto& addFunc : pendingComponents_) {
            auto result = addFunc(world_, id);
            if (!result) {
                world_.destroy_entity(id);
                return std::unexpected(result.error());
            }
        }

        pendingComponents_.clear();
        return id;
    }

private:
    World& world_;
    std::vector<std::function<std::expected<void, Error>(World&, EntityId)>> pendingComponents_;
};

// ============================================================================
// FREE FUNCTIONS
// ============================================================================

// Create entity with components in one call
template<Component... Ts>
[[nodiscard]] std::expected<EntityId, Error> create_entity_with(World& world, Ts... components) {
    EntityBuilder builder{world};
    (builder.with(std::move(components)), ...);
    return builder.build();
}

// Get or create component
template<Component T>
[[nodiscard]] T& get_or_add(World& world, EntityId id, T default_value = T{}) {
    if (auto comp = world.get_component<T>(id)) {
        return comp->get();
    }
    world.add_component(id, std::move(default_value));
    return world.get_component<T>(id)->get();
}

// Safe component access with fallback
template<Component T>
[[nodiscard]] const T& get_or_default(const World& world, EntityId id, const T& fallback = T{}) {
    if (auto comp = world.get_component<T>(id)) {
        return comp->get();
    }
    return fallback;
}

// Remove entity if it matches predicate
template<Component T, typename Pred>
void remove_if(World& world, Pred&& pred) {
    auto entities = world.query<T>();
    for (EntityId id : entities) {
        if (auto comp = world.get_component<T>(id)) {
            if (pred(comp->get())) {
                world.destroy_entity(id);
            }
        }
    }
}

} // namespace ecs

// ============================================================================
// DEMO / MAIN
// ============================================================================

int main() {
    using namespace ecs;

    std::println("=== C++23 ECS Demo ===\n");

    // Create the world
    World world;

    // Create some entities using the builder pattern
    auto player = EntityBuilder{world}
        .with(Position{0.0f, 0.0f, 0.0f})
        .with(Velocity{5.0f, 0.0f, 0.0f})
        .with(Health{100, 100})
        .with(Renderable{42, 1.0f, true})
        .with(Name{"Player"})
        .with(Tag{"player"})
        .build();

    auto enemy1 = EntityBuilder{world}
        .with(Position{10.0f, 0.0f, 5.0f})
        .with(Velocity{-2.0f, 0.0f, 0.0f})
        .with(Health{50, 50})
        .with(Renderable{100, 1.0f, true})
        .with(Name{"Goblin"})
        .with(Tag{"enemy"})
        .build();

    auto enemy2 = create_entity_with(world,
        Position{15.0f, 0.0f, -3.0f},
        Velocity{-3.0f, 0.0f, 0.0f},
        Health{75, 75},
        Renderable{101, 1.5f, true},
        Name{"Orc"},
        Tag{"enemy"}
    );

    auto prop = create_entity_with(world,
        Position{5.0f, 0.0f, 0.0f},
        Renderable{200, 2.0f, true},
        Name{"Tree"}
    );

    // Check for errors
    if (!player || !enemy1 || !enemy2 || !prop) {
        std::println("Error creating entities: {}", error_to_string(player.error()));
        return 1;
    }

    std::println("Created {} entities\n", world.entity_count());

    // Print initial state
    DebugSystem debug{world};
    debug.print_stats();
    std::println();

    // Print entity info
    std::println("--- Entity Info ---");
    debug.print_entity_info(player.value());
    debug.print_entity_info(enemy1.value());
    std::println();

    // Create systems
    MovementSystem movement{world};
    HealthSystem health{world};
    RenderSystem render{world};

    // Simulate game loop
    std::println("=== Simulating 3 frames ===\n");

    for (int frame = 1; frame <= 3; ++frame) {
        std::println("--- Frame {} ---", frame);

        // Update movement
        movement.update(0.016f); // ~60fps

        // Combat: player attacks enemy1
        if (frame == 1) {
            health.damage(enemy1.value(), 25);
            std::println("Player attacks {} for 25 damage!", 
                world.get_component<Name>(enemy1.value())->get().value);
        }
        if (frame == 2) {
            health.damage(enemy1.value(), 30);
            std::println("Player attacks {} for 30 damage!",
                world.get_component<Name>(enemy1.value())->get().value);
        }

        // Render
        std::println("Rendering:");
        render.update();

        // Check for dead entities
        auto dead = health.get_dead_entities();
        if (!dead.empty()) {
            std::println("Dead entities this frame:");
            for (EntityId id : dead) {
                auto name = world.get_component<Name>(id);
                std::println("  - Entity {} ({})", id, 
                    name ? name->get().value : "unnamed");
            }
        }

        std::println();
    }

    // Query examples
    std::println("=== Query Examples ===\n");

    // Query all entities with Position and Velocity
    auto moving = world.query<Position, Velocity>();
    std::println("Moving entities ({}):", moving.size());
    for (EntityId id : moving) {
        auto name = world.get_component<Name>(id);
        auto pos = world.get_component<Position>(id);
        std::println("  - {} at ({:.1f}, {:.1f}, {:.1f})",
            name ? name->get().value : "unnamed",
            pos->get().x, pos->get().y, pos->get().z);
    }
    std::println();

    // Query all enemies
    auto enemies = world.query<Tag>();
    std::println("Tagged entities ({}):", enemies.size());
    for (EntityId id : enemies) {
        auto tag = world.get_component<Tag>(id);
        auto name = world.get_component<Name>(id);
        std::println("  - {} [{}]", 
            name ? name->get().value : "unnamed",
            tag ? tag->get().value : "no tag");
    }
    std::println();

    // Demonstrate error handling with expected
    std::println("=== Error Handling Examples ===\n");

    // Try to get non-existent component
    auto result = world.get_component<Velocity>(prop.value());
    if (!result) {
        std::println("Tree has no velocity: {}", error_to_string(result.error()));
    }

    // Try to get component from invalid entity
    auto invalid = world.get_component<Position>(INVALID_ENTITY_ID);
    if (!invalid) {
        std::println("Invalid entity: {}", error_to_string(invalid.error()));
    }

    // Try to add duplicate component
    auto dup = world.add_component(player.value(), Position{1, 2, 3});
    if (!dup) {
        std::println("Duplicate component: {}", error_to_string(dup.error()));
    }
    std::println();

    // Demonstrate compile-time features
    std::println("=== Compile-time Features ===\n");
    std::println("Component index of Position: {}", component_index<Position>());
    std::println("Component index of Health: {}", component_index<Health>());
    std::println("Component name of Velocity: {}", component_name<Velocity>());
    std::println("Total component types: {}", component_count());
    std::println("Is valid entity ID 0: {}", is_valid_entity_id(0));
    std::println("Is valid entity ID 1: {}", is_valid_entity_id(1));

    // Compile-time component checks
    static_assert(Component<Position>);
    static_assert(Component<Velocity>);
    static_assert(Component<Health>);
    static_assert(!Component<int>);
    static_assert(!Component<std::string>);

    // Compile-time Position checks
    constexpr Position p1{};
    static_assert(p1.is_zero());
    constexpr Position p2{1.0f, 2.0f, 3.0f};
    static_assert(!p2.is_zero());

    // Compile-time Velocity checks
    constexpr Velocity v1{3.0f, 4.0f, 0.0f};
    static_assert(v1.magnitude_squared() == 25.0f);

    std::println();

    // Cleanup dead entities
    std::println("=== Cleanup ===\n");
    auto dead = health.get_dead_entities();
    for (EntityId id : dead) {
        auto name = world.get_component<Name>(id);
        std::println("Removing dead entity: {}", 
            name ? name->get().value : "unnamed");
        world.destroy_entity(id);
    }

    debug.print_stats();

    // Demonstrate get_or_add and get_or_default
    std::println("\n=== Utility Functions ===\n");
    
    // Add velocity to tree (it didn't have one)
    auto& treeVel = get_or_add(world, prop.value(), Velocity{0.0f, 0.0f, 1.0f});
    std::println("Tree now has velocity: ({:.1f}, {:.1f}, {:.1f})",
        treeVel.dx, treeVel.dy, treeVel.dz);

    // Get health with default
    const auto& treeHealth = get_or_default<Health>(world, prop.value(), Health{0, 0});
    std::println("Tree health (default): {}/{}", treeHealth.value, treeHealth.max);

    std::println("\n=== Demo Complete ===");

    return 0;
}