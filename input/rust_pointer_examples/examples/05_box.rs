// ============================================================================
// 5. Box<T> - HEAP ALLOCATION
// ============================================================================
// Box<T> is a smart pointer that puts data on the HEAP instead of the stack.
// - It has single ownership (like a regular variable, just on the heap).
// - It automatically frees memory when it goes out of scope (Drop trait).
// - It allows for recursive types (a struct containing itself).
// - It enables dynamic dispatch for trait objects (dyn Trait).

fn main() {
    // Basic heap allocation
    let boxed_num = Box::new(42);
    println!("Boxed number: {}", boxed_num);
    println!("Size of Box pointer on stack: {} bytes", std::mem::size_of_val(&boxed_num));

    // Mutable Box
    let mut boxed_str = Box::new(String::from("Hello"));
    boxed_str.push_str(", Heap!");
    println!("Mutable Box: {}", boxed_str);

    // RECURSIVE TYPES (Impossible without Box because compiler can't know size)
    enum List {
        Cons(i32, Box<List>),
        Nil,
    }
    let recursive_list = List::Cons(1, 
        Box::new(List::Cons(2, 
            Box::new(List::Cons(3, 
                Box::new(List::Nil))))));
    println!("Created recursive list successfully!");

    // DYNAMIC DISPATCH (Trait Objects)
    trait Animal { fn speak(&self); }
    struct Dog;
    struct Cat;
    impl Animal for Dog { fn speak(&self) { println!("  Woof!"); } }
    impl Animal for Cat { fn speak(&self) { println!("  Meow!"); } }

    // Vec of animals with different sizes, erased to a fat pointer (Box<dyn Animal>)
    let animals: Vec<Box<dyn Animal>> = vec![Box::new(Dog), Box::new(Cat)];
    for animal in animals {
        animal.speak();
    }
}
