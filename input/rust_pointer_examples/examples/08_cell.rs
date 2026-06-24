// ============================================================================
// 8. Cell<T> - INTERIOR MUTABILITY FOR COPY TYPES
// ============================================================================
// Cell<T> allows you to mutate data even when you only have an immutable 
// reference to the Cell itself.
// - ONLY works with types that implement Copy (i32, f64, bool, etc.).
// - .get() copies the value OUT of the cell.
// - .set() copies a new value INTO the cell.
// - No runtime borrow checking (unlike RefCell).

use std::cell::Cell;

fn main() {
    // A struct with a field we want to mutate, but we don't want the struct to be mut
    struct Counter {
        count: Cell<usize>,
    }

    let counter = Counter { count: Cell::new(0) };
    
    // We only have an immutable reference to counter!
    increment_counter(&counter);
    increment_counter(&counter);
    increment_counter(&counter);

    // get() returns a copied value
    println!("Final count: {}", counter.count.get());

    fn increment_counter(c: &Counter) {
        // set() replaces the value inside, even though `c` is not `&mut`
        c.count.set(c.count.get() + 1);
    }

    // Another example: swapping values
    let cell = Cell::new(10);
    let old_value = cell.replace(20); // Returns the old value
    println!("Replaced {} with 20", old_value);
}
