// ============================================================================
// 6. Rc<T> - REFERENCE COUNTING (Single Threaded)
// ============================================================================
// Rc<T> enables MULTIPLE OWNERS of the same data.
// - It keeps a count of how many owners exist.
// - When the count reaches 0, the data is dropped.
// - NOT thread-safe! (Use Arc<T> for threads).
// - Data is immutable. Use RefCell<T> inside if you need to mutate it.

use std::rc::Rc;

fn main() {
    // Create an Rc. Initial strong count is 1.
    let rc_a = Rc::new(String::from("Shared Data")));
    println!("Count after creation: {}", Rc::strong_count(&rc_a));

    // Cloning an Rc does NOT copy the data. It just increments the count.
    let rc_b = Rc::clone(&rc_a);
    let rc_c = Rc::clone(&rc_a);
    
    println!("Count after 2 clones: {}", Rc::strong_count(&rc_a));
    println!("rc_a: {}, rc_b: {}, rc_c: {}", rc_a, rc_b, rc_c);

    // Dropping one owner decrements the count
    drop(rc_b);
    println!("Count after dropping rc_b: {}", Rc::strong_count(&rc_a));

    // When rc_a and rc_c go out of scope here, count hits 0 and String is freed.
    
    // Use case: Graph structures (Multiple nodes pointing to one node)
    let shared_node = Rc::new(42);
    let branch1 = Rc::clone(&shared_node);
    let branch2 = Rc::clone(&shared_node);
    println!("
Graph branches share node: {} and {}", branch1, branch2);
}
