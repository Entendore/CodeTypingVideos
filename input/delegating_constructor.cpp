#include <iostream>
#include <string>
class Box {
    std::string name;
    int size;
public:
    Box() : Box("default", 0) {            // delegates to Box(string,int)
        std::cout << "Delegated default\n";
    }
    Box(std::string n, int s) : name(std::move(n)), size(s) {
        std::cout << "Target ctor: " << name << ", " << size << "\n";
    }
};
int main() {
    Box b;                 // first calls Box(string,int), then body
}