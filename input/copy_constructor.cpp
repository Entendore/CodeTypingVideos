#include <iostream>
class Box {
    int* data;
public:
    Box(int v) : data(new int(v)) {}
    Box(const Box& o) : data(new int(*o.data)) {     // copy ctor
        std::cout << "Copy ctor, value=" << *data << "\n";
    }
    ~Box() { delete data; }
};
int main() {
    Box a(7);
    Box b = a;            // copy
    Box c(a);             // also copy
}