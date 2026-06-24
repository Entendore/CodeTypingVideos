// ============================================================================
// 7. Arc<T> - ATOMIC REFERENCE COUNTING (Thread Safe)
// ============================================================================
// Arc<T> is exactly like Rc<T>, but it uses atomic operations for the counter,
// making it safe to share across threads.
// - Data is still immutable.
// - To mutate, wrap the inner data in a Mutex or RwLock: Arc<Mutex<T>>.

use std::sync::Arc;
use std::thread;

fn main() {
    // Create Arc
    let data = Arc::new(vec![1, 2, 3, 4, 5]);
    
    let mut handles = vec![];

    for i in 0..5 {
        // Arc::clone increments atomic count (cheap)
        let data_clone = Arc::clone(&data);
        
        // move captures data_clone and moves it into the new thread
        handles.push(thread::spawn(move || {
            // Because of Arc, multiple threads can safely read this simultaneously
            println!("Thread {} sees data: {:?}", i, *data_clone);
        }));
    }

    for handle in handles {
        handle.join().unwrap();
    }
    
    println!("Main thread still owns data: {:?}", *data);
}
