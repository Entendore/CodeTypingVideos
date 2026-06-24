#include <iostream>
#include <string>
#include <utility>

class Base {
public:
    Base() { std::cout << "Base default\n"; }
    Base(int) { std::cout << "Base(int)\n"; }
};

class Demo : public Base {
    std::string name;
    int* data;
    size_t size;
public:
    // 1) Default constructor
    Demo() : Demo("unknown", 0) {            // delegates to another ctor
        std::cout << "  -> Default ctor\n";
    }

    // 2) Parameterized constructor
    Demo(std::string n, size_t s)
        : Base(1), name(std::move(n)), size(s) {
        data = s ? new int[s]{0} : nullptr;
        std::cout << "  -> Parameterized ctor\n";
    }

    // 3) Copy constructor
    Demo(const Demo& o) : Base(), name(o.name), size(o.size) {
        data = size ? new int[size] : nullptr;
        std::copy(o.data, o.data + size, data);
        std::cout << "  -> Copy ctor\n";
    }

    // 4) Move constructor
    Demo(Demo&& o) noexcept
        : Base(), name(std::move(o.name)), data(o.data), size(o.size) {
        o.data = nullptr;
        o.size = 0;
        std::cout << "  -> Move ctor\n";
    }

    // 5) Conversion constructor (explicit)
    explicit Demo(int x) : Demo("from_int", 1) {
        data[0] = x;
        std::cout << "  -> Conversion ctor (int)\n";
    }

    // 6) Inherited constructor from Base
    using Base::Base;

    // 7) Defaulted & Deleted
    Demo(double) = delete;                  // disallow implicit double

    ~Demo() { delete[] data; }
};

int main() {
    Demo d1;                  // default
    Demo d2("box", 3);        // parameterized
    Demo d3 = d2;             // copy
    Demo d4 = std::move(d3);  // move
    Demo d5(42);              // conversion (int)
    Demo d6((const Base&){}); // inherited Base()
    // Demo d7 = 3.14;        // ERROR: deleted ctor
    return 0;
}