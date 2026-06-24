// ============================================================================
// 3. RAW POINTERS - IMMUTABLE (*const T)
// ============================================================================
// *const T is an unsafe raw pointer. 
// - It CAN be null.
// - It does NOT enforce Rust's borrowing rules.
// - Creating it is safe, but READING (dereferencing) it requires `unsafe`.
// - Used primarily for FFI (Foreign Function Interface) with C libraries.

fn main() {
    let data: i32 = 100;
    
    // Creating a raw pointer from a reference is SAFE
    let raw_ptr: *const i32 = &data as *const i32;
    
    // Raw pointers can be null
    let null_ptr: *const i32 = std::ptr::null();
    
    println!("Raw pointer address: {:p}", raw_ptr);
    println!("Is null pointer null? {}", null_ptr.is_null());

    // DEREFERENCING requires an unsafe block. 
    // You are promising the compiler this memory is valid.
    unsafe {
        let value = *raw_ptr;
        println!("Dereferenced value: {}", value);
    }

    // Array pointer arithmetic
    let arr = [10, 20, 30, 40, 50];
    let arr_ptr: *const i32 = arr.as_ptr();
    
    unsafe {
        // .add(n) moves the pointer forward by n * size_of::<T>() bytes
        let third_element = arr_ptr.add(2); 
        println!("Third element via raw pointer: {}", *third_element);
    }
}
