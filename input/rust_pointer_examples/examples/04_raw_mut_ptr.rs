// ============================================================================
// 4. RAW POINTERS - MUTABLE (*mut T)
// ============================================================================
// *mut T allows mutation through the pointer, but requires `unsafe` to BOTH 
// read and write. Breaking aliasing rules with raw pointers causes Undefined Behavior.

fn main() {
    let mut data: i32 = 42;
    
    // Create mutable raw pointer
    let mut_ptr: *mut i32 = &mut data as *mut i32;
    
    // WRITING through raw pointer (unsafe)
    unsafe {
        *mut_ptr = 999;
    }
    println!("After raw write: {}", data);

    // Raw allocation using std::alloc
    use std::alloc::{alloc, dealloc, Layout};
    
    // Create a layout for a single i32
    let layout = Layout::new::<i32>();
    
    unsafe {
        // Allocate memory
        let ptr = alloc(layout) as *mut i32;
        
        if !ptr.is_null() {
            // Write to unallocated memory
            *ptr = 12345;
            println!("Allocated and wrote: {}", *ptr);
            
            // YOU MUST FREE THIS MEMORY. Rust won't do it for raw pointers.
            dealloc(ptr as *mut u8, layout);
            println!("Memory deallocated.");
        }
    }
}
