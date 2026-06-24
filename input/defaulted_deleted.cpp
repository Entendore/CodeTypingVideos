#include <iostream>
class Box {
    int w;
public:
    Box() = default;            // compiler-generated default
    Box(int) = delete;          // forbid int construction
    Box(double d) : w(int(d)) { // allowed
        std::cout << "Box(double) = " << w << "\n";
    }
};
int main() {
    Box a;            // OK: defaulted
    Box b(2.5);       // OK
    // Box c(3);      // ERROR: deleted
}