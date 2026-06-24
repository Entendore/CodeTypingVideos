// ============================================================================
// 10. Weak<T> - WEAK REFERENCES (Breaking Cycles)
// ============================================================================
// Weak<T> is a non-owning reference to Rc<T> or Arc<T>.
// - It does NOT increment the strong count.
// - The data CAN be dropped even if Weak references exist.
// - You must call .upgrade() which returns Option<Rc<T>>. 
//   (None if data was dropped, Some if still alive).
// - Used to prevent memory leaks in circular references (like parent/child or graphs).

use std::rc::{Rc, Weak};
use std::cell::RefCell;

struct Node {
    value: i32,
    // Use Weak to point to parent to avoid a reference cycle leak!
    parent: RefCell<Weak<Node>>, 
    children: RefCell<Vec<Rc<Node>>>,
}

fn main() {
    let root = Rc::new(Node {
        value: 1,
        parent: RefCell::new(Weak::new()),
        children: RefCell::new(vec![]),
    });

    let child = Rc::new(Node {
        value: 2,
        parent: RefCell::new(Rc::downgrade(&root)), // Weak reference!
        children: RefCell::new(vec![]),
    });

    root.children.borrow_mut().push(Rc::clone(&child));

    // Child accessing parent via Weak
    let parent_weak = child.parent.borrow().clone();
    
    if let Some(parent_strong) = parent_weak.upgrade() {
        println!("Child's parent value: {}", parent_strong.value);
    } else {
        println!("Parent was dropped!");
    }
    
    // If root is dropped here, parent_weak.upgrade() would return None.
}
