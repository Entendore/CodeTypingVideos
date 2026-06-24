// ============================================================================
// 2. MUTABLE REFERENCES (&mut T)
// ============================================================================
// &mut T allows you to modify borrowed data. 
// CRITICAL RULE: You can have ONLY ONE &mut T at a time, and no &T can exist 
// at the same time. This is Rust's "aliasing XOR mutability" guarantee.

fn main() {
    let mut number = 10;
    
    // Create a mutable reference
    let num_ref = &mut number;
    
    // Modify the data through the reference using the * (dereference) operator
    *num_ref = 20;
    
    // After the mutation, the reference is still used here
    println!("Modified number: {}", num_ref);
    
    // Once num_ref goes out of scope, we can borrow `number` again
    let second_ref = &mut number;
    *second_ref += 5;
    println!("Further modified: {}", second_ref);

    // NON-OVERLAPPING BORROWS
    // The compiler is smart enough to allow mutable borrows of different struct fields
    struct Point { x: i32, y: i32 }
    let mut p = Point { x: 1, y: 2 };
    
    let x_ref = &mut p.x;
    let y_ref = &mut p.y; // This is OK! Different fields.
    
    *x_ref = 10;
    *y_ref = 20;
    println!("Point x: {}, y: {}", p.x, p.y);
}
