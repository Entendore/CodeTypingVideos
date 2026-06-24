// spinning_cube.cpp
// Compile with: g++ -std=c++23 -I/usr/include/GL spinning_cube.cpp -lGL -lGLU -lglfw -o spinning_cube

#include <GL/glew.h>
#include <GLFW/glfw3.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>

#include <memory>
#include <expected>
#include <variant>
#include <vector>
#include <array>
#include <string_view>
#include <print>
#include <source_location>
#include <concepts>

//=============================================================================
// C++23 Feature Demonstrations
//=============================================================================

// constinit - guaranteed compile-time initialization, no static init order issues
constinit const double PI = 3.14159265358979323846;

// consteval - MUST be evaluated at compile time
consteval float deg_to_rad(float degrees) noexcept {
    return static_cast<float>(degrees * PI / 180.0);
}

// constexpr - CAN be evaluated at compile time
constexpr float rad_to_deg(float radians) noexcept {
    return static_cast<float>(radians * 180.0 / PI);
}

// consteval string literal concatenation for shader sources
consteval std::string_view vertex_shader_preamble() noexcept {
    return "#version 330 core\n"
           "layout (location = 0) in vec3 aPos;\n"
           "layout (location = 1) in vec3 aColor;\n"
           "layout (location = 2) in vec2 aTexCoord;\n";
}

consteval std::string_view fragment_shader_preamble() noexcept {
    return "#version 330 core\n";
}

//=============================================================================
// Error Handling with std::expected and std::variant
//=============================================================================

// Variant to represent different types of errors
enum class ErrorCategory : uint8_t {
    Initialization,
    ShaderCompilation,
    ShaderLinking,
    WindowCreation,
    OpenGL
};

struct GlError {
    ErrorCategory category;
    std::string message;
    std::source_location location;
    
    [[nodiscard]] std::string to_string() const {
        return std::format("[{}:{}] {} (Category: {})",
            location.file_name(),
            location.line(),
            message,
            static_cast<int>(category));
    }
};

// Type alias for expected with our error type
template<typename T>
using GlResult = std::expected<T, GlError>;

// Helper macro for creating errors with source location
#define GL_ERROR(category, msg) \
    GlError{category, msg, std::source_location::current()}

//=============================================================================
// RAII Wrappers with Smart Pointers
//=============================================================================

// Custom deleters for OpenGL resources
struct GlShaderDeleter {
    void operator()(GLuint* shader) const noexcept {
        if (shader && *shader) {
            glDeleteShader(*shader);
        }
        delete shader;
    }
};

struct GlProgramDeleter {
    void operator()(GLuint* program) const noexcept {
        if (program && *program) {
            glDeleteProgram(*program);
        }
        delete program;
    }
};

struct GlBufferDeleter {
    void operator()(GLuint* buffer) const noexcept {
        if (buffer && *buffer) {
            glDeleteBuffers(1, buffer);
        }
        delete buffer;
    }
};

struct GlVaoDeleter {
    void operator()(GLuint* vao) const noexcept {
        if (vao && *vao) {
            glDeleteVertexArrays(1, vao);
        }
        delete vao;
    }
};

struct GlTextureDeleter {
    void operator()(GLuint* texture) const noexcept {
        if (texture && *texture) {
            glDeleteTextures(1, texture);
        }
        delete texture;
    }
};

struct GlfwWindowDeleter {
    void operator()(GLFWwindow** window) const noexcept {
        if (window && *window) {
            glfwDestroyWindow(*window);
            delete window;
        }
    }
};

// Smart pointer type aliases
using GlShaderPtr = std::unique_ptr<GLuint, GlShaderDeleter>;
using GlProgramPtr = std::unique_ptr<GLuint, GlProgramDeleter>;
using GlBufferPtr = std::unique_ptr<GLuint, GlBufferDeleter>;
using GlVaoPtr = std::unique_ptr<GLuint, GlVaoDeleter>;
using GlTexturePtr = std::unique_ptr<GLuint, GlTextureDeleter>;
using GlfwWindowPtr = std::unique_ptr<GLFWwindow*, GlfwWindowDeleter>;

//=============================================================================
// Shader Compilation with Expected
//=============================================================================

GlResult<GlShaderPtr> compile_shader(GLenum type, std::string_view source,
                                      std::source_location loc = std::source_location::current()) 
{
    GLuint shader = glCreateShader(type);
    if (shader == 0) {
        return std::unexpected(GL_ERROR(ErrorCategory::ShaderCompilation, 
            "Failed to create shader object"));
    }
    
    const GLchar* src = source.data();
    GLint length = static_cast<GLint>(source.length());
    glShaderSource(shader, 1, &src, &length);
    glCompileShader(shader);
    
    GLint success;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    
    if (!success) {
        std::array<GLchar, 512> info_log{};
        glGetShaderInfoLog(shader, sizeof(info_log), nullptr, info_log.data());
        glDeleteShader(shader);
        return std::unexpected(GL_ERROR(ErrorCategory::ShaderCompilation,
            std::format("Shader compilation failed: {}", info_log.data())));
    }
    
    return GlShaderPtr(new GLuint(shader));
}

GlResult<GlProgramPtr> link_program(const GlShaderPtr& vertex, const GlShaderPtr& fragment,
                                     std::source_location loc = std::source_location::current())
{
    GLuint program = glCreateProgram();
    if (program == 0) {
        return std::unexpected(GL_ERROR(ErrorCategory::ShaderLinking,
            "Failed to create program object"));
    }
    
    glAttachShader(program, *vertex);
    glAttachShader(program, *fragment);
    glLinkProgram(program);
    
    GLint success;
    glGetProgramiv(program, GL_LINK_STATUS, &success);
    
    if (!success) {
        std::array<GLchar, 512> info_log{};
        glGetProgramInfoLog(program, sizeof(info_log), nullptr, info_log.data());
        glDeleteProgram(program);
        return std::unexpected(GL_ERROR(ErrorCategory::ShaderLinking,
            std::format("Program linking failed: {}", info_log.data())));
    }
    
    return GlProgramPtr(new GLuint(program));
}

//=============================================================================
// Cube Geometry - constexpr where possible
//=============================================================================

// Concept for 3D vector-like types
template<typename T>
concept Vec3Like = requires(T v) {
    { v.x } -> std::convertible_to<float>;
    { v.y } -> std::convertible_to<float>;
    { v.z } -> std::convertible_to<float>;
};

struct Vertex {
    float x, y, z;
    float r, g, b;
    float u, v;
};

// constexpr vertex generation
consteval std::array<Vertex, 36> generate_cube_vertices() noexcept {
    return {{
        // Front face
        {{-0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {0.0f, 0.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {0.0f, 1.0f, 0.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {1.0f, 1.0f}},
        {{-0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {0.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {1.0f, 1.0f}},
        {{-0.5f,  0.5f,  0.5f}, {1.0f, 1.0f, 0.0f}, {0.0f, 1.0f}},
        // Back face
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 1.0f}, {1.0f, 1.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {1.0f, 1.0f, 1.0f}, {0.0f, 1.0f}},
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {1.0f, 1.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f, -0.5f}, {0.5f, 0.5f, 0.5f}, {0.0f, 0.0f}},
        // Top face
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 1.0f}, {0.0f, 1.0f}},
        {{-0.5f,  0.5f,  0.5f}, {1.0f, 1.0f, 0.0f}, {0.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {1.0f, 1.0f, 1.0f}, {1.0f, 1.0f}},
        // Bottom face
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f, -0.5f}, {0.5f, 0.5f, 0.5f}, {1.0f, 1.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {0.0f, 1.0f, 0.0f}, {1.0f, 0.0f}},
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {0.0f, 1.0f, 0.0f}, {1.0f, 0.0f}},
        {{-0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {0.0f, 0.0f}},
        // Right face
        {{ 0.5f, -0.5f, -0.5f}, {0.5f, 0.5f, 0.5f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f, -0.5f}, {1.0f, 1.0f, 1.0f}, {1.0f, 1.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f, -0.5f}, {0.5f, 0.5f, 0.5f}, {1.0f, 0.0f}},
        {{ 0.5f,  0.5f,  0.5f}, {0.0f, 0.0f, 1.0f}, {0.0f, 1.0f}},
        {{ 0.5f, -0.5f,  0.5f}, {0.0f, 1.0f, 0.0f}, {0.0f, 0.0f}},
        // Left face
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {0.0f, 0.0f}},
        {{-0.5f, -0.5f,  0.5f}, {1.0f, 0.0f, 0.0f}, {1.0f, 0.0f}},
        {{-0.5f,  0.5f,  0.5f}, {1.0f, 1.0f, 0.0f}, {1.0f, 1.0f}},
        {{-0.5f, -0.5f, -0.5f}, {1.0f, 0.0f, 1.0f}, {0.0f, 0.0f}},
        {{-0.5f,  0.5f,  0.5f}, {1.0f, 1.0f, 0.0f}, {1.0f, 1.0f}},
        {{-0.5f,  0.5f, -0.5f}, {0.0f, 1.0f, 1.0f}, {0.0f, 1.0f}},
    }};
}

// Verify at compile time
static_assert(generate_cube_vertices().size() == 36, "Cube must have 36 vertices");

//=============================================================================
// Variant-based configuration system
//=============================================================================

struct WindowConfig {
    int width;
    int height;
    std::string title;
    bool fullscreen;
};

struct RenderConfig {
    bool wireframe;
    bool vsync;
    int msaa_samples;
};

struct AnimationConfig {
    float rotation_speed_x;
    float rotation_speed_y;
    float rotation_speed_z;
    bool auto_rotate;
};

// Variant to hold different configuration types
using ConfigVariant = std::variant<WindowConfig, RenderConfig, AnimationConfig>;

// Visitor for configuration handling
struct ConfigPrinter {
    void operator()(const WindowConfig& cfg) const {
        std::print("Window: {}x{}, title='{}', fullscreen={}\n",
            cfg.width, cfg.height, cfg.title, cfg.fullscreen);
    }
    
    void operator()(const RenderConfig& cfg) const {
        std::print("Render: wireframe={}, vsync={}, msaa={}\n",
            cfg.wireframe, cfg.vsync, cfg.msaa_samples);
    }
    
    void operator()(const AnimationConfig& cfg) const {
        std::print("Animation: speed=({},{},{}), auto_rotate={}\n",
            cfg.rotation_speed_x, cfg.rotation_speed_y, cfg.rotation_speed_z,
            cfg.auto_rotate);
    }
};

//=============================================================================
// Mesh class with smart pointer managed resources
//=============================================================================

class Mesh {
public:
    static GlResult<std::unique_ptr<Mesh>> create(const std::span<const Vertex> vertices) {
        auto mesh = std::make_unique<Mesh>();
        
        // Create VAO
        GLuint vao;
        glGenVertexArrays(1, &vao);
        mesh->vao_ = GlVaoPtr(new GLuint(vao));
        
        // Create VBO
        GLuint vbo;
        glGenBuffers(1, &vbo);
        mesh->vbo_ = GlBufferPtr(new GLuint(vbo));
        
        // Bind VAO
        glBindVertexArray(*mesh->vao_);
        
        // Bind and fill VBO
        glBindBuffer(GL_ARRAY_BUFFER, *mesh->vbo_);
        glBufferData(GL_ARRAY_BUFFER, 
                     vertices.size() * sizeof(Vertex),
                     vertices.data(),
                     GL_STATIC_DRAW);
        
        // Position attribute
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 
                              sizeof(Vertex), 
                              reinterpret_cast<void*>(offsetof(Vertex, x)));
        glEnableVertexAttribArray(0);
        
        // Color attribute
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE,
                              sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, r)));
        glEnableVertexAttribArray(1);
        
        // Texture coordinate attribute
        glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE,
                              sizeof(Vertex),
                              reinterpret_cast<void*>(offsetof(Vertex, u)));
        glEnableVertexAttribArray(2);
        
        // Unbind
        glBindVertexArray(nullptr);
        
        mesh->vertex_count_ = static_cast<GLsizei>(vertices.size());
        
        return mesh;
    }
    
    void draw() const noexcept {
        glBindVertexArray(*vao_);
        glDrawArrays(GL_TRIANGLES, 0, vertex_count_);
        glBindVertexArray(nullptr);
    }
    
    [[nodiscard]] GLsizei vertex_count() const noexcept { return vertex_count_; }
    
private:
    Mesh() = default;
    
    GlVaoPtr vao_;
    GlBufferPtr vbo_;
    GLsizei vertex_count_{0};
};

//=============================================================================
// Application State - using variant for state machine
//=============================================================================

enum class AppState : uint8_t {
    Initializing,
    Running,
    Paused,
    ShuttingDown,
    Error
};

struct RunningState {
    float delta_time;
    double total_time;
};

struct PausedState {
    float saved_delta_time;
};

struct ErrorState {
    GlError error;
};

using StateVariant = std::variant<
    std::monostate,  // Initializing
    RunningState,
    PausedState,
    std::monostate,  // ShuttingDown
    ErrorState
>;

//=============================================================================
// Main Application Class
//=============================================================================

class SpinningCubeApp {
public:
    static GlResult<std::unique_ptr<SpinningCubeApp>> create() {
        auto app = std::make_unique<SpinningCubeApp>();
        
        // Initialize GLFW
        if (!glfwInit()) {
            return std::unexpected(GL_ERROR(ErrorCategory::Initialization,
                "Failed to initialize GLFW"));
        }
        
        // Configure GLFW
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
        glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
        glfwWindowHint(GLFW_SAMPLES, 4);
        
        // Create window
        GLFWwindow* window = glfwCreateWindow(
            window_config_.width,
            window_config_.height,
            window_config_.title.c_str(),
            window_config_.fullscreen ? glfwGetPrimaryMonitor() : nullptr,
            nullptr
        );
        
        if (!window) {
            glfwTerminate();
            return std::unexpected(GL_ERROR(ErrorCategory::WindowCreation,
                "Failed to create GLFW window"));
        }
        
        // Use smart pointer with custom deleter
        app->window_ = GlfwWindowPtr(new GLFWwindow*(window));
        
        glfwMakeContextCurrent(window);
        glfwSetFramebufferSizeCallback(window, framebuffer_size_callback);
        glfwSetKeyCallback(window, key_callback);
        glfwSetWindowUserPointer(window, app.get());
        
        // Initialize GLEW
        glewExperimental = GL_TRUE;
        if (glewInit() != GLEW_OK) {
            return std::unexpected(GL_ERROR(ErrorCategory::Initialization,
                "Failed to initialize GLEW"));
        }
        
        // Enable depth testing and MSAA
        glEnable(GL_DEPTH_TEST);
        glEnable(GL_MULTISAMPLE);
        
        // Compile shaders
        auto vertex_shader = compile_shader(GL_VERTEX_SHADER, get_vertex_shader_source());
        if (!vertex_shader) {
            return std::unexpected(vertex_shader.error());
        }
        
        auto fragment_shader = compile_shader(GL_FRAGMENT_SHADER, get_fragment_shader_source());
        if (!fragment_shader) {
            return std::unexpected(fragment_shader.error());
        }
        
        // Link program
        auto program = link_program(*vertex_shader, *fragment_shader);
        if (!program) {
            return std::unexpected(program.error());
        }
        app->shader_program_ = std::move(program);
        
        // Create mesh
        constexpr auto vertices = generate_cube_vertices();
        auto mesh = Mesh::create(vertices);
        if (!mesh) {
            return std::unexpected(mesh.error());
        }
        app->mesh_ = std::move(*mesh);
        
        // Generate procedural texture
        auto texture = create_checkerboard_texture();
        if (!texture) {
            return std::unexpected(texture.error());
        }
        app->texture_ = std::move(*texture);
        
        // Print configuration using variant visitor
        std::print("=== Configuration ===\n");
        std::visit(ConfigPrinter{}, 
                   static_cast<ConfigVariant>(window_config_));
        std::visit(ConfigPrinter{},
                   static_cast<ConfigVariant>(render_config_));
        std::visit(ConfigPrinter{},
                   static_cast<ConfigVariant>(animation_config_));
        std::print("=====================\n\n");
        
        return app;
    }
    
    void run() {
        state_ = RunningState{0.0f, 0.0};
        
        double last_time = glfwGetTime();
        
        while (!glfwWindowShouldClose(**window_)) {
            auto* running = std::get_if<RunningState>(&state_);
            if (!running) {
                if (auto* err = std::get_if<ErrorState>(&state_)) {
                    std::print(stderr, "Error: {}\n", err->error.to_string());
                    break;
                }
                continue;
            }
            
            double current_time = glfwGetTime();
            running->delta_time = static_cast<float>(current_time - last_time);
            running->total_time = current_time;
            last_time = current_time;
            
            process_input();
            update(*running);
            render();
            
            glfwSwapBuffers(**window_);
            glfwPollEvents();
        }
    }
    
    ~SpinningCubeApp() {
        if (window_) {
            glfwTerminate();
        }
    }
    
    // Delete copy, allow move
    SpinningCubeApp(const SpinningCubeApp&) = delete;
    SpinningCubeApp& operator=(const SpinningCubeApp&) = delete;
    SpinningCubeApp(SpinningCubeApp&&) = default;
    SpinningCubeApp& operator=(SpinningCubeApp&&) = default;
    
private:
    SpinningCubeApp() = default;
    
    static void framebuffer_size_callback(GLFWwindow* window, int width, int height) {
        glViewport(0, 0, width, height);
    }
    
    static void key_callback(GLFWwindow* window, int key, int scancode, 
                             int action, int mods) {
        auto* app = static_cast<SpinningCubeApp*>(glfwGetWindowUserPointer(window));
        if (!app) return;
        
        if (key == GLFW_KEY_ESCAPE && action == GLFW_PRESS) {
            glfwSetWindowShouldClose(window, GLFW_TRUE);
        }
        
        if (key == GLFW_KEY_SPACE && action == GLFW_PRESS) {
            // Toggle pause state using variant
            if (std::holds_alternative<RunningState>(app->state_)) {
                auto running = std::get<RunningState>(app->state_);
                app->state_ = PausedState{running.delta_time};
                std::print("Paused\n");
            } else if (std::holds_alternative<PausedState>(app->state_)) {
                app->state_ = RunningState{0.0f, glfwGetTime()};
                std::print("Resumed\n");
            }
        }
        
        if (key == GLFW_KEY_W && action == GLFW_PRESS) {
            app->render_config_.wireframe = !app->render_config_.wireframe;
            glPolygonMode(GL_FRONT_AND_BACK, 
                app->render_config_.wireframe ? GL_LINE : GL_FILL);
            std::print("Wireframe: {}\n", app->render_config_.wireframe);
        }
    }
    
    void process_input() {
        // Additional input processing could go here
    }
    
    void update(const RunningState& state) {
        if (!animation_config_.auto_rotate) return;
        
        rotation_x += animation_config_.rotation_speed_x * state.delta_time;
        rotation_y += animation_config_.rotation_speed_y * state.delta_time;
        rotation_z += animation_config_.rotation_speed_z * state.delta_time;
    }
    
    void render() {
        glClearColor(0.1f, 0.1f, 0.15f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        
        glUseProgram(**shader_program_);
        
        // Bind texture
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, **texture_);
        glUniform1i(glGetUniformLocation(**shader_program_, "texture1"), 0);
        
        // Create transformation matrices
        glm::mat4 model = glm::mat4(1.0f);
        model = glm::rotate(model, deg_to_rad(rotation_x), glm::vec3(1.0f, 0.0f, 0.0f));
        model = glm::rotate(model, deg_to_rad(rotation_y), glm::vec3(0.0f, 1.0f, 0.0f));
        model = glm::rotate(model, deg_to_rad(rotation_z), glm::vec3(0.0f, 0.0f, 1.0f));
        
        glm::mat4 view = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -3.0f));
        
        int width, height;
        glfwGetFramebufferSize(**window_, &width, &height);
        float aspect = static_cast<float>(width) / static_cast<float>(height);
        glm::mat4 projection = glm::perspective(deg_to_rad(45.0f), aspect, 0.1f, 100.0f);
        
        // Set uniforms
        GLuint model_loc = glGetUniformLocation(**shader_program_, "model");
        GLuint view_loc = glGetUniformLocation(**shader_program_, "view");
        GLuint proj_loc = glGetUniformLocation(**shader_program_, "projection");
        
        glUniformMatrix4fv(model_loc, 1, GL_FALSE, glm::value_ptr(model));
        glUniformMatrix4fv(view_loc, 1, GL_FALSE, glm::value_ptr(view));
        glUniformMatrix4fv(proj_loc, 1, GL_FALSE, glm::value_ptr(projection));
        
        // Draw mesh
        mesh_->draw();
        
        glUseProgram(0);
    }
    
    static std::string_view get_vertex_shader_source() {
        static const std::string source = std::string(vertex_shader_preamble()) +
            "out vec3 ourColor;\n"
            "out vec2 TexCoord;\n"
            "uniform mat4 model;\n"
            "uniform mat4 view;\n"
            "uniform mat4 projection;\n"
            "void main() {\n"
            "    gl_Position = projection * view * model * vec4(aPos, 1.0);\n"
            "    ourColor = aColor;\n"
            "    TexCoord = aTexCoord;\n"
            "}\n";
        return source;
    }
    
    static std::string_view get_fragment_shader_source() {
        static const std::string source = std::string(fragment_shader_preamble()) +
            "in vec3 ourColor;\n"
            "in vec2 TexCoord;\n"
            "out vec4 FragColor;\n"
            "uniform sampler2D texture1;\n"
            "void main() {\n"
            "    vec4 texColor = texture(texture1, TexCoord);\n"
            "    FragColor = mix(vec4(ourColor, 1.0), texColor, 0.5);\n"
            "}\n";
        return source;
    }
    
    static GlResult<GlTexturePtr> create_checkerboard_texture() {
        constexpr int tex_width = 8;
        constexpr int tex_height = 8;
        
        // Generate checkerboard pattern at compile time
        consteval auto generate_checkerboard() {
            std::array<std::array<glm::vec4, tex_width>, tex_height> data{};
            for (int y = 0; y < tex_height; ++y) {
                for (int x = 0; x < tex_width; ++x) {
                    bool white = (x + y) % 2 == 0;
                    data[y][x] = white ? glm::vec4(1.0f, 1.0f, 1.0f, 1.0f) 
                                       : glm::vec4(0.2f, 0.2f, 0.2f, 1.0f);
                }
            }
            return data;
        }
        
        constexpr auto tex_data = generate_checkerboard();
        
        GLuint texture;
        glGenTextures(1, &texture);
        
        glBindTexture(GL_TEXTURE_2D, texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tex_width, tex_height, 0,
                     GL_RGBA, GL_FLOAT, tex_data.data());
        
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
        
        glBindTexture(GL_TEXTURE_2D, nullptr);
        
        return GlTexturePtr(new GLuint(texture));
    }
    
    // Smart pointer managed resources
    GlfwWindowPtr window_;
    GlProgramPtr shader_program_;
    std::unique_ptr<Mesh> mesh_;
    GlTexturePtr texture_;
    
    // Configuration (constinit where possible)
    static inline constinit WindowConfig window_config_{800, 600, "Spinning Cube (C++23)", false};
    static inline constinit RenderConfig render_config_{false, true, 4};
    static inline constinit AnimationConfig animation_config_{45.0f, 60.0f, 0.0f, true};
    
    // State using variant
    StateVariant state_{std::monostate{}};
    
    // Rotation angles
    float rotation_x{0.0f};
    float rotation_y{0.0f};
    float rotation_z{0.0f};
};

//=============================================================================
// Entry Point
//=============================================================================

int main() {
    // Demonstrate consteval at compile time
    constexpr float test_angle = deg_to_rad(90.0f);
    constexpr float test_back = rad_to_deg(test_angle);
    static_assert(test_back == 90.0f, "Degree/radian conversion must be reversible");
    
    std::print("Spinning Cube Demo - C++23 Features\n");
    std::print("===================================\n");
    std::print("Controls:\n");
    std::print("  ESC   - Quit\n");
    std::print("  SPACE - Pause/Resume\n");
    std::print("  W     - Toggle wireframe\n\n");
    
    // Create application using expected for error handling
    auto app_result = SpinningCubeApp::create();
    
    if (!app_result) {
        std::print(stderr, "Failed to create application:\n  {}\n", 
                   app_result.error().to_string());
        return 1;
    }
    
    // Run the application
    app_result->run();
    
    std::print("\nApplication exited cleanly.\n");
    return 0;
}