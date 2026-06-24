#include <iostream>
class Money {
    double amount;
public:
    Money(double d) : amount(d) {                 // implicit conversion ctor
        std::cout << "Implicit conversion from double\n";
    }
    explicit Money(int cents) : amount(cents/100.0) {  // explicit only
        std::cout << "Explicit conversion from int\n";
    }
    void show() { std::cout << amount << "\n"; }
};
int main() {
    Money m1 = 9.5;        // OK: implicit double -> Money
    // Money m2 = 500;     // ERROR: explicit prevents implicit
    Money m3(500);         // OK: explicit call
    m1.show(); m3.show();
}