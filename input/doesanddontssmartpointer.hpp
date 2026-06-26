#include <iostream>
#include <memory>
#include <vector>
#include <string>

// ============================================================================
// SMART POINTERS IN C++ - DO'S AND DON'TS
// ============================================================================

/*
 * SMART POINTERS OVERVIEW:
 * - std::unique_ptr: Exclusive ownership, non-copyable, movable
 * - std::shared_ptr: Shared ownership, reference counted
 * - std::weak_ptr: Non-owning reference to objects managed by shared_ptr
 */

class Widget {
private:
    std::string name;
    int value;
public:
    Widget(const std::string& n, int v) : name(n), value(v) {
        std::cout << "  [CTOR] Widget '" << name << "' created\n";
    }
    ~Widget() {
        std::cout << "  [DTOR] Widget '" << name << "' destroyed\n";
    }
    void show() const {
        std::cout << "  Widget: " << name << " = " << value << "\n";
    }
    void setValue(int v) { value = v; }
    int getValue() const { return value; }
};

// Helper function to print section headers
void printHeader(const std::string& title) {
    std::cout << "\n" << std::string(60, '=') << "\n";
    std::cout << " " << title << "\n";
    std::cout << std::string(60, '=') << "\n";
}

void printSubHeader(const std::string& title) {
    std::cout << "\n--- " << title << " ---\n";
}

// ============================================================================
// SECTION 1: UNIQUE_PTR - DO'S
// ============================================================================
void uniquePtrDos() {
    printHeader("UNIQUE_PTR - DO'S ✅");

    printSubHeader("DO #1: Use make_unique for creation (C++14+)");
    std::cout << "  Reason: Single allocation, exception-safe, more efficient\n";
    auto w1 = std::make_unique<Widget>("GoodWidget1", 100);
    w1->show();

    printSubHeader("DO #2: Use unique_ptr as function parameters by reference");
    std::cout << "  Reason: Avoids ownership transfer when not needed\n";
    auto processWidget = [](std::unique_ptr<Widget>& w) {
        w->setValue(w->getValue() + 10);
        std::cout << "  Processed: ";
        w->show();
    };
    processWidget(w1);

    printSubHeader("DO #3: Use unique_ptr for factory functions (return by value)");
    std::cout << "  Reason: Clean ownership transfer, moves are efficient\n";
    auto createWidget = []() -> std::unique_ptr<Widget> {
        return std::make_unique<Widget>("FactoryWidget", 200);
    };
    auto w2 = createWidget();
    w2->show();

    printSubHeader("DO #4: Use unique_ptr with custom deleters when needed");
    std::cout << "  Reason: Proper cleanup for non-standard resources\n";
    auto customDeleter = [](Widget* w) {
        std::cout << "  [CUSTOM DELETER] Deleting ";
        delete w;
    };
    std::unique_ptr<Widget, decltype(customDeleter)> w3(
        new Widget("CustomDeleterWidget", 300), customDeleter
    );
    w3->show();

    printSubHeader("DO #5: Use unique_ptr in containers");
    std::cout << "  Reason: Automatic cleanup when container is destroyed\n";
    std::vector<std::unique_ptr<Widget>> widgets;
    widgets.push_back(std::make_unique<Widget>("Container1", 401));
    widgets.push_back(std::make_unique<Widget>("Container2", 402));
    std::cout << "  Widgets in container:\n";
    for (const auto& w : widgets) {
        w->show();
    }
    std::cout << "  (Container will clean up automatically)\n";
}

// ============================================================================
// SECTION 2: UNIQUE_PTR - DON'TS
// ============================================================================
void uniquePtrDonts() {
    printHeader("UNIQUE_PTR - DON'TS ❌");

    printSubHeader("DON'T #1: Don't use 'new' directly (prefer make_unique)");
    std::cout << "  ❌ BAD:  std::unique_ptr<Widget> w(new Widget(...));\n";
    std::cout << "  ✅ GOOD: auto w = std::make_unique<Widget>(...);\n";
    std::cout << "  Reason: 'new' can leak if constructor throws, make_unique is safer\n\n";

    printSubHeader("DON'T #2: Don't copy unique_ptr");
    std::cout << "  ❌ BAD CODE (won't compile):\n";
    std::cout << "     auto w1 = std::make_unique<Widget>(\"A\", 1);\n";
    std::cout << "     auto w2 = w1;  // ERROR: copy is deleted!\n";
    std::cout << "  ✅ GOOD: Use std::move() if transfer is intended:\n";
    std::cout << "     auto w2 = std::move(w1);\n\n";

    printSubHeader("DON'T #3: Don't use unique_ptr for shared ownership");
    std::cout << "  If multiple owners needed, use shared_ptr instead\n";
    std::cout << "  unique_ptr means EXCLUSIVE ownership\n\n";

    printSubHeader("DON'T #4: Don't release() unless you have a good reason");
    std::cout << "  ❌ BAD:  auto* raw = w.release();  // Now YOU must delete!\n";
    std::cout << "  ✅ GOOD: Just let unique_ptr handle it, or use reset()\n\n";

    printSubHeader("DON'T #5: Don't create unique_ptr from raw pointer twice");
    std::cout << "  ❌ FATAL ERROR (double delete):\n";
    std::cout << "     Widget* raw = new Widget(\"Danger\", 0);\n";
    std::cout << "     auto p1 = std::unique_ptr<Widget>(raw);\n";
    std::cout << "     auto p2 = std::unique_ptr<Widget>(raw);  // DOUBLE DELETE!\n";
    std::cout << "  ✅ GOOD: Always use make_unique() to avoid this\n";
}

// ============================================================================
// SECTION 3: SHARED_PTR - DO'S
// ============================================================================
void sharedPtrDos() {
    printHeader("SHARED_PTR - DO'S ✅");

    printSubHeader("DO #1: Use make_shared for creation");
    std::cout << "  Reason: Single allocation (control block + object), more efficient\n";
    auto w1 = std::make_shared<Widget>("SharedWidget1", 500);
    std::cout << "  use_count: " << w1.use_count() << "\n";

    printSubHeader("DO #2: Share ownership when needed");
    {
        auto w2 = w1;  // Both share ownership
        std::cout << "  After sharing - w1 use_count: " << w1.use_count() << "\n";
        std::cout << "  After sharing - w2 use_count: " << w2.use_count() << "\n";
        w2->show();
    }
    std::cout << "  After w2 destroyed - w1 use_count: " << w1.use_count() << "\n";

    printSubHeader("DO #3: Pass shared_ptr by value when sharing ownership");
    std::cout << "  Reason: Increases reference count, ensures object survives\n";
    auto shareOwnership = [](std::shared_ptr<Widget> w) {
        std::cout << "  Inside function - use_count: " << w.use_count() << "\n";
        w->show();
    };
    shareOwnership(w1);
    std::cout << "  After function - use_count: " << w1.use_count() << "\n";

    printSubHeader("DO #4: Use weak_ptr to break circular references");
    std::cout << "  Reason: Prevents memory leaks in cyclic structures\n";
    std::cout << "  (See weak_ptr section for full example)\n";

    printSubHeader("DO #5: Check use_count() for debugging (not logic)");
    std::cout << "  Current use_count: " << w1.use_count() << "\n";
    std::cout << "  Note: Don't base control flow on use_count\n";
}

// ============================================================================
// SECTION 4: SHARED_PTR - DON'TS
// ============================================================================
void sharedPtrDonts() {
    printHeader("SHARED_PTR - DON'TS ❌");

    printSubHeader("DON'T #1: Don't use shared_ptr when unique_ptr suffices");
    std::cout << "  ❌ BAD:  auto w = std::make_shared<Widget>(\"X\", 1);\n";
    std::cout << "           // If only one owner needed, this is overkill\n";
    std::cout << "  ✅ GOOD: auto w = std::make_unique<Widget>(\"X\", 1);\n";
    std::cout << "  Reason: unique_ptr has zero overhead, shared_ptr has atomic ref counting\n\n";

    printSubHeader("DON'T #2: Don't create shared_ptr from 'this' directly");
    std::cout << "  ❌ BAD:  std::shared_ptr<Widget> sp(this);\n";
    std::cout << "           // Creates NEW control block -> DOUBLE DELETE!\n";
    std::cout << "  ✅ GOOD: Inherit from std::enable_shared_from_this<Widget>\n";
    std::cout << "           Then use: shared_from_this()\n\n";

    printSubHeader("DON'T #3: Don't create multiple shared_ptrs from same raw pointer");
    std::cout << "  ❌ FATAL ERROR:\n";
    std::cout << "     Widget* raw = new Widget(\"Bad\", 0);\n";
    std::cout << "     auto sp1 = std::shared_ptr<Widget>(raw);\n";
    std::cout << "     auto sp2 = std::shared_ptr<Widget>(raw);  // DOUBLE DELETE!\n";
    std::cout << "  ✅ GOOD: auto sp1 = std::make_shared<Widget>(\"Good\", 1);\n";
    std::cout << "           auto sp2 = sp1;  // Share same control block\n\n";

    printSubHeader("DON'T #4: Don't use shared_ptr for caches/observers");
    std::cout << "  ❌ BAD:  Cache holds shared_ptr -> objects never freed\n";
    std::cout << "  ✅ GOOD: Use weak_ptr for caches, observers, etc.\n\n";

    printSubHeader("DON'T #5: Don't pass shared_ptr when you don't need ownership");
    std::cout << "  ❌ BAD:  void func(shared_ptr<Widget> w)  // Unnecessary copy\n";
    std::cout << "  ✅ GOOD: void func(Widget& w)       // If no ownership needed\n";
    std::cout << "           void func(Widget* w)       // If nullable and no ownership\n";
    std::cout << "           void func(const shared_ptr<Widget>& w)  // If might need to copy\n";
}

// ============================================================================
// SECTION 5: WEAK_PTR - DO'S AND DON'TS
// ============================================================================
void weakPtrSection() {
    printHeader("WEAK_PTR - DO'S AND DON'TS");

    printSubHeader("DO: Use weak_ptr to break circular references");
    std::cout << "  Example: Parent-Child relationship\n";
    
    // Simulating the pattern (simplified)
    auto parent = std::make_shared<Widget>("Parent", 1);
    std::weak_ptr<Widget> weakChild;
    
    {
        auto child = std::make_shared<Widget>("Child", 2);
        weakChild = child;  // Parent holds weak_ptr to child
        std::cout << "  Child use_count: " << child.use_count() << "\n";
        std::cout << "  Child locked: " << (weakChild.lock() ? "yes" : "no") << "\n";
    }  // Child destroyed here (no circular reference!)
    
    std::cout << "  After child destroyed - weakChild locked: " 
              << (weakChild.lock() ? "yes" : "no") << "\n";

    printSubHeader("DO: Use lock() to safely access weak_ptr");
    std::cout << "  Always check if lock() returns non-null:\n";
    std::cout << "  ✅ GOOD:\n";
    std::cout << "     if (auto sp = weak.lock()) {\n";
    std::cout << "         sp->doSomething();  // Safe!\n";
    std::cout << "     } else {\n";
    std::cout << "         // Object was destroyed\n";
    std::cout << "     }\n\n";

    printSubHeader("DON'T: Don't use weak_ptr without checking lock()");
    std::cout << "  ❌ BAD:\n";
    std::cout << "     auto sp = weak.lock();\n";
    std::cout << "     sp->doSomething();  // CRASH if expired!\n\n";

    printSubHeader("DON'T: Don't use weak_ptr as a primary owner");
    std::cout << "  weak_ptr doesn't keep object alive - use shared_ptr for ownership\n";

    printSubHeader("DO: Use weak_ptr for observer pattern");
    std::cout << "  Observers shouldn't keep subjects alive\n";
    std::cout << "  weak_ptr allows checking if subject still exists\n";

    printSubHeader("DO: Use expired() for quick checks (no allocation)");
    std::cout << "  if (!weak.expired()) { /* might still be expired by lock() */ }\n";
    std::cout << "  Better: Always use lock() and check result\n";
}

// ============================================================================
// SECTION 6: ENABLE_SHARED_FROM_THIS
// ============================================================================
class SafeWidget : public std::enable_shared_from_this<SafeWidget> {
    std::string name;
public:
    SafeWidget(const std::string& n) : name(n) {
        std::cout << "  [CTOR] SafeWidget '" << name << "' created\n";
    }
    ~SafeWidget() {
        std::cout << "  [DTOR] SafeWidget '" << name << "' destroyed\n";
    }
    
    // ✅ CORRECT: Get shared_ptr to self
    std::shared_ptr<SafeWidget> getSelf() {
        return shared_from_this();
    }
    
    void show() const {
        std::cout << "  SafeWidget: " << name << "\n";
    }
};

void enableSharedFromThisSection() {
    printHeader("ENABLE_SHARED_FROM_THIS - CORRECT USAGE");

    printSubHeader("Correct: Create with make_shared, then use shared_from_this()");
    auto safeW = std::make_shared<SafeWidget>("SafeExample");
    std::cout << "  Original use_count: " << safeW.use_count() << "\n";
    
    auto selfPtr = safeW->getSelf();
    std::cout << "  After getSelf() use_count: " << safeW.use_count() << "\n";
    std::cout << "  selfPtr points to same object: " 
              << (safeW.get() == selfPtr.get() ? "YES" : "NO") << "\n";

    printSubHeader("⚠️  IMPORTANT: Object MUST be managed by shared_ptr first!");
    std::cout << "  ❌ CRASH: SafeWidget* raw = new SafeWidget(\"X\");\n";
    std::cout << "              raw->getSelf();  // BAD_WEAK_PTR exception!\n";
    std::cout << "  ✅ GOOD:  auto sp = std::make_shared<SafeWidget>(\"X\");\n";
    std::cout << "              sp->getSelf();  // Works!\n";
}

// ============================================================================
// SECTION 7: PERFORMANCE CONSIDERATIONS
// ============================================================================
void performanceSection() {
    printHeader("PERFORMANCE CONSIDERATIONS");

    std::cout << "\n  📊 Memory Overhead:\n";
    std::cout << "  ┌─────────────────┬────────────────────────────┐\n";
    std::cout << "  │ Raw Pointer     │ 0 bytes (just address)     │\n";
    std::cout << "  │ unique_ptr      │ 0 bytes (same as raw ptr)  │\n";
    std::cout << "  │ shared_ptr      │ 16 bytes (ptr + control*)  │\n";
    std::cout << "  │ weak_ptr        │ 16 bytes (ptr + control*)  │\n";
    std::cout << "  └─────────────────┴────────────────────────────┘\n";

    std::cout << "\n  📊 Control Block Overhead (shared_ptr):\n";
    std::cout << "  ┌─────────────────────────────────────────┐\n";
    std::cout << "  │ Strong count (atomic)     : 8 bytes     │\n";
    std::cout << "  │ Weak count (atomic)       : 8 bytes     │\n";
    std::cout << "  │ Deleter + Allocator       : ~16 bytes   │\n";
    std::cout << "  │ Total: ~32 bytes          │             │\n";
    std::cout << "  └─────────────────────────────────────────┘\n";

    std::cout << "\n  ⚡ Performance Tips:\n";
    std::cout << "  1. Prefer unique_ptr over shared_ptr (no atomic overhead)\n";
    std::cout << "  2. Use make_shared/make_unique (single allocation)\n";
    std::cout << "  3. Pass shared_ptr by const& if not transferring ownership\n";
    std::cout << "  4. Avoid unnecessary copies of shared_ptr\n";
    std::cout << "  5. Consider raw pointers for non-owning, non-null references\n";
}

// ============================================================================
// SECTION 8: QUICK REFERENCE CHEAT SHEET
// ============================================================================
void cheatSheet() {
    printHeader("QUICK REFERENCE CHEAT SHEET");

    std::cout << R"(
  ╔═══════════════════════════════════════════════════════════════╗
  ║                    WHEN TO USE WHAT                          ║
  ╠═══════════════════════════════════════════════════════════════╣
  ║  SCENARIO                    │ USE THIS                       ║
  ╠═════════════════════════════╪═════════════════════════════════╣
  ║  Single owner               │ unique_ptr                     ║
  ║  Multiple owners            │ shared_ptr                     ║
  ║  Non-owning reference       │ raw pointer or reference       ║
  ║  Non-owning, might expire   │ weak_ptr                       ║
  ║  Breaking cycles            │ weak_ptr + shared_ptr          ║
  ║  Factory returns ownership  │ unique_ptr (or shared if needed)║
  ║  Observer pattern           │ weak_ptr                       ║
  ║  Cache                      │ weak_ptr                       ║
  ║  Optional ownership         │ unique_ptr (check with get())  ║
  ╚═════════════════════════════╧═════════════════════════════════╝

  ╔═══════════════════════════════════════════════════════════════╗
  ║                    CREATION PATTERNS                         ║
  ╠═══════════════════════════════════════════════════════════════╣
  ║  auto up = std::make_unique<T>(args...);   // C++14+        ║
  ║  auto sp = std::make_shared<T>(args...);   // Always        ║
  ║  std::weak_ptr<T> wp = sp;                 // From shared   ║
  ╚═══════════════════════════════════════════════════════════════╝

  ╔═══════════════════════════════════════════════════════════════╗
  ║                    COMMON OPERATIONS                         ║
  ╠═══════════════════════════════════════════════════════════════╣
  ║  ptr.get()          → Get raw pointer (don't delete it!)    ║
  ║  ptr.reset()        → Destroy current object, optionally set new║
  ║  ptr.release()      → Relinquish ownership (unique only)    ║
  ║  ptr.use_count()    → Get reference count (shared only)     ║
  ║  wp.lock()          → Get shared_ptr (empty if expired)     ║
  ║  wp.expired()       → Check if object destroyed             ║
  ╚═══════════════════════════════════════════════════════════════╝
)";
}

// ============================================================================
// MAIN FUNCTION
// ============================================================================
int main() {
    std::cout << "\n";
    std::cout << "╔══════════════════════════════════════════════════════════════╗\n";
    std::cout << "║     C++ SMART POINTERS: DO'S AND DON'TS GUIDE                ║\n";
    std::cout << "║                                                              ║\n";
    std::cout << "║  Learn the RIGHT way to use smart pointers and avoid         ║\n";
    std::cout << "║  common pitfalls that lead to bugs and memory leaks!         ║\n";
    std::cout << "╚══════════════════════════════════════════════════════════════╝\n";

    // Run all sections
    uniquePtrDos();
    uniquePtrDonts();
    sharedPtrDos();
    sharedPtrDonts();
    weakPtrSection();
    enableSharedFromThisSection();
    performanceSection();
    cheatSheet();

    std::cout << "\n";
    std::cout << "╔══════════════════════════════════════════════════════════════╗\n";
    std::cout << "║                         SUMMARY                              ║\n";
    std::cout << "╠══════════════════════════════════════════════════════════════╣\n";
    std::cout << "║  ✅ USE make_unique/make_shared - never raw new              ║\n";
    std::cout << "║  ✅ USE unique_ptr by default - it's zero-overhead           ║\n";
    std::cout << "║  ✅ USE shared_ptr ONLY when you need shared ownership       ║\n";
    std::cout << "║  ✅ USE weak_ptr to break cycles and for observers          ║\n";
    std::cout << "║  ✅ USE enable_shared_from_this for self-referencing        ║\n";
    std::cout << "║                                                              ║\n";
    std::cout << "║  ❌ DON'T mix raw pointers and smart pointers for same obj  ║\n";
    std::cout << "║  ❌ DON'T create multiple smart ptrs from same raw ptr      ║\n";
    std::cout << "║  ❌ DON'T use shared_from_this on unmanaged objects         ║\n";
    std::cout << "║  ❌ DON'T use release() unless absolutely necessary         ║\n";
    std::cout << "║  ❌ DON'T pass smart_ptr when raw ptr/ref suffices          ║\n";
    std::cout << "╚══════════════════════════════════════════════════════════════╝\n";
    std::cout << "\n";

    return 0;
}