#include <iostream>
class Box {
    int w, h;
public:
    Box() {                 // default constructor (no args)
        w = 0; h = 0;
        std::cout << "Default ctor\n";
    }
};
int main() {
    Box b;                  // calls Box()
}