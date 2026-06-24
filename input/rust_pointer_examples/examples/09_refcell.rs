// ============================================================================
// 9. RefCell<T> - RUNTIME BORROW CHECKING
// ============================================================================
// RefCell<T> enforces borrowing rules at RUNTIME instead of COMPILE TIME.
// - .borrow() returns a Ref<T> (like &T). Panics if already mutably borrowed.
// - .borrow_mut() returns a RefMut<T> (like &mut T). Panics if already borrowed.
// - Use this when the compiler can't prove your borrowing is safe, but you know it is.
// - NOT thread-safe.

use std::cell::RefCell;

fn main() {
    let ref_cell = RefCell::new(String::from("Hello"));
    
    // Immutable borrow
    let r1 = ref_cell.borrow();
    println!("Borrowed immutably: {}", *r1);
    drop(r1); // MUST drop r1 before mutable borrow, or it will PANIC!

    // Mutable borrow
    let mut r2 = ref_cell.borrow_mut();
    r2.push_str(", World!");
    drop(r2); // Release the lock

    println!("After mutation: {}", ref_cell.borrow());

    // Safe checking with try_borrow
    let r3 = ref_cell.borrow();
    match ref_cell.try_borrow_mut() {
        Ok(_) => println!("This won't print"),
        Err(e) => println!("Safe error catch: {}", e), // Catches the panic!
    }
}
