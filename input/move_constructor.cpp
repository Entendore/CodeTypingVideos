#include <iostream>
#include <utility>
class Box {
    int* data;
public:
    Box(int v) : data(new int(v)) {}
    Box(Box&& o) noexcept : data(o.data) {            // move ctor
        o.data = nullptr;
        std::cout << "Move ctor\n";
    }
    ~Box() { delete data; }
};
int main() {
    Box a(5);
    Box b = std::move(a);    // move
}