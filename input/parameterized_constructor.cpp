#include <iostream>
class Box {
    int w, h;
public:
    Box(int w_, int h_) : w(w_), h(h_) {   // parameterized ctor
        std::cout << "Parameterized ctor: " << w << "x" << h << "\n";
    }
};
int main() {
    Box b(3, 4);
}