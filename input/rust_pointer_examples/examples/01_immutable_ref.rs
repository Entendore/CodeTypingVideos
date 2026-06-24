// ============================================================================
// 1. IMMUTABLE REFERENCES (&T)
// ============================================================================
// &T is a borrowed reference. It allows you to read data but not modify it.
// You can have as many &T references to the same data as you want simultaneously.
// It has zero runtime cost and is guaranteed by the compiler to never be null.

fn main() {
    let data = 42;
    
    // Creating multiple immutable references is perfectly valid
    let ref1 = &data;
    let ref2 = &data;
    
    println!("Data: {}", data);
    println!("Reference 1: {}", ref1);
    println!("Reference 2: {}", ref2);
    println!("Memory address of ref1: {:p}", ref1);
    println!("Memory address of ref2: {:p}", ref2);
    
    // References can also point to slices
    let arr = [10, 20, 30, 40, 50];
    let slice: &[i32] = &arr[1..4]; // Borrows elements 20, 30, 40
    println!("Slice reference: {:?}", slice);
    
    // Passing references to functions (borrowing instead of moving)
    print_length(&arr);
}

fn print_length(items: &[i32]) {
    // We don't own the array, we just borrowed a slice of it
    println!("Length of borrowed slice: {}", items.len());
}
