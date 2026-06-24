#include <iostream>
class Base {
public:
    Base()        { std::cout << "Base()\n"; }
    Base(int x)   { std::cout << "Base(" << x << ")\n"; }
    Base(int x,int y){ std::cout << "Base("<<x<<","<<y<<")\n"; }
};
class Derived : public Base {
public:
    using Base::Base;       // inherit ALL Base constructors
};
int main() {
    Derived d1;             // -> Base()
    Derived d2(5);          // -> Base(int)
    Derived d3(2, 3);       // -> Base(int,int)
}