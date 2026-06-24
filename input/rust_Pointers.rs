// ============================================================================
// COMPLETE RUST POINTERS GUIDE
// ============================================================================
// Rust has several pointer types for different purposes:
//
// 1. REFERENCES (Safe Pointers):
//    - &T     : Immutable reference (shared borrow)
//    - &mut T : Mutable reference (exclusive borrow)
//
// 2. RAW POINTERS (Unsafe):
//    - *const T : Immutable raw pointer
//    - *mut T   : Mutable raw pointer
//
// 3. SMART POINTERS (std::smart pointers):
//    - Box<T>        : Heap allocation, single ownership
//    - Rc<T>         : Reference counting, single-threaded
//    - Arc<T>        : Atomic reference counting, thread-safe
//    - RefCell<T>    : Runtime borrow checking, interior mutability
//    - Cell<T>       : Copy types with interior mutability
//    - Weak<T>       : Weak reference to Rc/Arc
//    - Cow<T>        : Clone-on-write
//    - Mutex<T>      : Mutual exclusion lock
//    - RwLock<T>     : Read-write lock
//    - OnceCell<T>   : Lazy one-time initialization
//    - Pin<T>        : Pinning for self-referential types
// ============================================================================

use std::cell::{Cell, RefCell, OnceCell, Ref, RefMut};
use std::collections::HashMap;
use std::ffi::c_void;
use std::ops::Deref;
use std::ptr::{self, NonNull};
use std::rc::{Rc, Weak as RcWeak};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, RwLock, Weak as ArcWeak, OnceLock};
use std::thread;

fn main() {
    println!("{}", "=".repeat(75));
    println!("              COMPLETE RUST POINTERS GUIDE");
    println!("{}", "=".repeat(75));

    // ========================================================================
    // 1. IMMUTABLE REFERENCES (&T)
    // ========================================================================
    section_header("1. IMMUTABLE REFERENCES (&T)");

    /*
    WHAT IS &T?
    - A "borrowed" pointer to data owned by someone else
    - Read-only access
    - Guaranteed to point to valid data (no null)
    - Follows borrowing rules: multiple &T allowed simultaneously
    - Zero runtime cost (compiled away)
    - MUST NOT outlive the data it points to (lifetime enforced)
    */

    let data = 42;                    // data lives on stack
    let reference: &i32 = &data;      // reference borrows data

    println!("data value: {}", data);
    println!("reference value: {}", reference);
    println!("reference points to: {:p}", reference);  // memory address
    println!("data address:        {:p}", &data as *const i32);

    // Multiple immutable references are allowed
    let ref1 = &data;
    let ref2 = &data;
    let ref3 = &data;
    println!("\nMultiple immutable refs: {}, {}, {}", ref1, ref2, ref3);

    // Reference to reference
    let double_ref: &&i32 = &ref1;
    println!("Double reference: {}", double_ref);

    // Reference to a slice
    let arr = [1, 2, 3, 4, 5];
    let slice: &[i32] = &arr[1..4];  // points to elements [2, 3, 4]
    println!("\nSlice reference: {:?}", slice);

    // Reference to struct field
    struct Point { x: i32, y: i32 }
    let point = Point { x: 10, y: 20 };
    let x_ref: &i32 = &point.x;
    println!("Field reference: {}", x_ref);

    println!("\nKEY RULES FOR &T:");
    println!("  • Can have multiple &T at the same time");
    println!("  • Cannot modify data through &T");
    println!("  • Cannot have &mut T while &T exists");
    println!("  • Must live shorter than the owned data");
    println!("  • No null - always points to valid data");

    // ========================================================================
    // 2. MUTABLE REFERENCES (&mut T)
    // ========================================================================
    section_header("2. MUTABLE REFERENCES (&mut T)");

    /*
    WHAT IS &mut T?
    - Exclusive mutable borrow
    - Allows modification of borrowed data
    - ONLY ONE &mut T allowed at a time
    - No other references (&T or &mut T) can exist simultaneously
    - Used for "in-place" modification without taking ownership
    */

    let mut number = 10;
    println!("Before: number = {}", number);

    // Create mutable reference
    let num_ref: &mut i32 = &mut number;
    *num_ref = 20;  // Dereference and assign
    println!("After:  number = {}", number);

    // Mutable reference to struct
    struct Person { name: String, age: u32 }
    let mut person = Person {
        name: String::from("Alice"),
        age: 30,
    };

    modify_age(&mut person);
    println!("\nAfter modify_age: {} is {} years old", person.name, person.age);

    // Mutable slice
    let mut nums = [1, 2, 3, 4, 5];
    let slice: &mut [i32] = &mut nums[1..4];
    slice[0] = 100;  // Modifies nums[1]
    println!("\nAfter slice modification: {:?}", nums);

    // Reborrowing - temporarily creating a new reference from &mut
    let mut value = 5;
    let mut_ref = &mut value;
    // *mut_ref can be reborrowed as immutable within the scope
    let reborrowed: &i32 = &*mut_ref;
    println!("\nReborrowed as immutable: {}", reborrowed);
    // mut_ref is still usable after reborrowed goes out of scope

    println!("\nKEY RULES FOR &mut T:");
    println!("  • ONLY ONE &mut T at a time (exclusive access)");
    println!("  • No &T can exist while &mut T exists");
    println!("  • Allows modification through dereference (*ref)");
    println!("  • Must live shorter than the owned data");
    println!("  • Enables "aliasing XOR mutability" guarantee");

    // ========================================================================
    // 3. BORROWING RULES VISUALIZED
    // ========================================================================
    section_header("3. BORROWING RULES - EXAMPLES");

    // VALID: Multiple immutable borrows
    let mut x = 1;
    let r1 = &x;
    let r2 = &x;
    println!("Valid: r1={}, r2={}", r1, r2);

    // VALID: Mutable borrow after immutable borrows end
    let r3 = &mut x;
    *r3 += 1;
    println!("Valid after immutable ends: x={}", x);

    // INVALID (commented out - won't compile):
    // let r1 = &x;
    // let r2 = &mut x;  // ERROR! Cannot borrow mutably while borrowed immutably
    // println!("{}, {}", r1, r2);

    // INVALID (commented out):
    // let r1 = &mut x;
    // let r2 = &mut x;  // ERROR! Cannot borrow mutably more than once
    // println!("{}, {}", r1, r2);

    // VALID: Non-overlapping mutable borrows through different paths
    let mut point = Point { x: 1, y: 2 };
    let x = &mut point.x;
    let y = &mut point.y;  // OK: different fields, compiler understands
    *x = 10;
    *y = 20;
    println!("Non-overlapping field borrows: ({}, {})", point.x, point.y);

    // ========================================================================
    // 4. RAW POINTERS - *const T
    // ========================================================================
    section_header("4. RAW POINTERS - *const T (IMMUTABLE)");

    /*
    WHAT IS *const T?
    - Raw pointer to immutable data
    - UNSAFE to dereference
    - Can be null
    - No ownership semantics
    - No lifetime checking
    - No aliasing guarantees
    - Created in safe code, used in unsafe blocks
    */

    let data: i32 = 100;

    // Create raw pointer from reference (safe operation)
    let raw_ptr: *const i32 = &data as *const i32;
    println!("Raw pointer address: {:p}", raw_ptr);

    // Can be null
    let null_ptr: *const i32 = std::ptr::null();
    println!("Null pointer: {:p}", null_ptr);
    println!("Is null: {}", null_ptr.is_null());

    // Dereferencing requires unsafe block
    let value: i32 = unsafe { *raw_ptr };
    println!("Dereferenced value: {}", value);

    // Raw pointer to array
    let arr = [10, 20, 30, 40, 50];
    let arr_ptr: *const i32 = arr.as_ptr();

    println!("\nArray via raw pointer:");
    unsafe {
        for i in 0..5 {
            // Pointer arithmetic
            let element_ptr = arr_ptr.add(i);
            println!("  arr[{}] = {} (at {:p})", i, *element_ptr, element_ptr);
        }
    }

    // Raw pointer to struct
    struct MyStruct { a: i32, b: i32 }
    let my_struct = MyStruct { a: 1, b: 2 };
    let struct_ptr: *const MyStruct = &my_struct;
    unsafe {
        println!("\nStruct via raw pointer: a={}, b={}", (*struct_ptr).a, (*struct_ptr).b);
    }

    // Raw pointer to unsized type (slice)
    let slice = [1, 2, 3];
    let slice_ptr: *const [i32] = &slice[..];
    unsafe {
        println!("\nSlice via raw pointer: {:?}, len={}", *slice_ptr, (*slice_ptr).len());
    }

    println!("\nKEY POINTS ABOUT *const T:");
    println!("  • Created safely, dereferenced unsafely");
    println!("  • Can be null (no guaranteed validity)");
    println!("  • No borrowing rules enforced");
    println!("  • No lifetime checking");
    println!("  • Used for FFI, low-level operations");

    // ========================================================================
    // 5. RAW POINTERS - *mut T
    // ========================================================================
    section_header("5. RAW POINTERS - *mut T (MUTABLE)");

    /*
    WHAT IS *mut T?
    - Raw pointer to potentially mutable data
    - UNSAFE to read or write through
    - Can be null
    - No aliasing rules enforced (but breaking them is UB!)
    - Can be created from &mut T or from raw allocation
    */

    let mut data: i32 = 42;
    let mut_ptr: *mut i32 = &mut data as *mut i32;
    println!("Mutable raw pointer: {:p}", mut_ptr);

    // Write through raw pointer (unsafe)
    unsafe {
        *mut_ptr = 100;
    }
    println!("After write through *mut: data = {}", data);

    // Read through raw pointer (unsafe)
    let read_value: i32 = unsafe { *mut_ptr };
    println!("Read through *mut: {}", read_value);

    // null_mut() for null mutable pointer
    let null_mut: *mut i32 = std::ptr::null_mut();
    println!("\nNull mutable pointer: {:p}", null_mut);

    // Pointer arithmetic with *mut
    let mut arr = [1, 2, 3, 4, 5];
    let mut ptr: *mut i32 = arr.as_mut_ptr();
    unsafe {
        for i in 0..5 {
            *ptr.add(i) *= 10;  // Multiply each element by 10
        }
    }
    println!("\nAfter pointer arithmetic modification: {:?}", arr);

    // Creating raw pointer from scratch (without reference)
    let layout = std::alloc::Layout::new::<i32>();
    let raw_alloc: *mut i32 = unsafe { std::alloc::alloc(layout) as *mut i32 };
    if !raw_alloc.is_null() {
        unsafe {
            *raw_alloc = 999;
            println!("\nAllocated via raw alloc: {}", *raw_alloc);
            std::alloc::dealloc(raw_alloc as *mut u8, layout);
        }
    }

    // *mut to *const coercion (implicit)
    let const_ptr: *const i32 = mut_ptr;  // *mut -> *const is safe
    println!("\n*mut coerced to *const: {:p}", const_ptr);

    println!("\nKEY POINTS ABOUT *mut T:");
    println!("  • Can mutate data (but unsafe)");
    println!("  • Creating from &mut T is safe");
    println!("  • Reading/writing requires unsafe");
    println!("  • Alias with &T or &mut T = Undefined Behavior!");
    println!("  • Use for FFI, custom allocators");

    // ========================================================================
    // 6. Box<T> - HEAP ALLOCATION
    // ========================================================================
    section_header("6. Box<T> - HEAP ALLOCATION");

    /*
    WHAT IS Box<T>?
    - Smart pointer that allocates T on the heap
    - Single ownership (like String, but for any type)
    - Automatically freed when Box goes out of scope
    - Zero runtime overhead (no reference counting)
    - Implements Deref and DerefMut
    - Size is always one pointer (regardless of T's size)
    */

    // Basic Box creation
    let boxed: Box<i32> = Box::new(42);
    println!("Boxed value: {}", boxed);
    println!("Box size: {} bytes", std::mem::size_of::<Box<i32>>());
    println!("Boxed i32 size on heap: {} bytes", std::mem::size_of::<i32>());

    // Box with large data (avoids stack overflow)
    let large_data: Box<[u64; 10000]> = Box::new([0u64; 10000]);
    println!("\nLarge array on heap: {} elements", large_data.len());
    println!("Box size (just ptr): {} bytes", std::mem::size_of_val(&large_data));
    println!("Data size on heap: {} bytes", std::mem::size_of_val(&*large_data));

    // Mutable Box
    let mut mutable_box: Box<i32> = Box::new(10);
    *mutable_box = 20;  // Dereference and modify
    println!("\nMutable Box: {}", mutable_box);

    // Box with struct
    struct TreeNode {
        value: i32,
        left: Option<Box<TreeNode>>,
        right: Option<Box<TreeNode>>,
    }

    let tree = TreeNode {
        value: 1,
        left: Some(Box::new(TreeNode {
            value: 2,
            left: None,
            right: None,
        })),
        right: Some(Box::new(TreeNode {
            value: 3,
            left: Some(Box::new(TreeNode {
                value: 4,
                left: None,
                right: None,
            })),
            right: None,
        })),
    };
    println!("\nBinary tree (recursive Box):");
    print_tree(&tree, 0);

    // Box for dynamic dispatch (trait objects)
    trait Animal {
        fn speak(&self);
    }
    struct Dog;
    struct Cat;
    impl Animal for Dog {
        fn speak(&self) { println!("  Dog says: Woof!"); }
    }
    impl Animal for Cat {
        fn speak(&self) { println!("  Cat says: Meow!"); }
    }

    let animals: Vec<Box<dyn Animal>> = vec![
        Box::new(Dog),
        Box::new(Cat),
    ];
    println!("\nDynamic dispatch with Box<dyn Trait>:");
    for animal in &animals {
        animal.speak();
    }

    // Box for unsized types (slices, str, dyn Trait)
    let boxed_slice: Box<[i32]> = vec![1, 2, 3].into_boxed_slice();
    println!("\nBoxed slice: {:?}", boxed_slice);

    let boxed_str: Box<str> = "Hello, Box!".into();
    println!("Boxed str: {}", boxed_str);

    // Deref coercion
    fn takes_slice(s: &[i32]) {
        println!("Function received slice: {:?}", s);
    }
    let boxed_vec = Box::new(vec![1, 2, 3]);
    takes_slice(&boxed_vec);  // Box<Vec<i32>> -> &Vec<i32> -> &[i32]

    // Box::leak - convert to 'static reference (forget to deallocate)
    let leaked: &'static i32 = Box::leak(Box::new(999));
    println!("\nLeaked Box (never freed): {}", leaked);

    println!("\nKEY POINTS ABOUT Box<T>:");
    println!("  • Single ownership, moved when assigned");
    println!("  • Automatically deallocated on drop");
    println!("  • Enables recursive data structures");
    println!("  • Enables dynamic dispatch (dyn Trait)");
    println!("  • Can hold unsized types");
    println!("  • Zero runtime overhead");

    // ========================================================================
    // 7. Rc<T> - REFERENCE COUNTING (SINGLE THREAD)
    // ========================================================================
    section_header("7. Rc<T> - REFERENCE COUNTING");

    /*
    WHAT IS Rc<T>?
    - Reference counted smart pointer
    - Multiple owners of same data
    - NOT thread-safe (use Arc for threads)
    - Data freed when count reaches 0
    - Immutable access only (use RefCell for interior mutability)
    - Cloning increments reference count (cheap)
    */

    // Basic Rc usage
    let rc1: Rc<i32> = Rc::new(42);
    println!("Created Rc: {}", rc1);
    println!("Reference count: {}", Rc::strong_count(&rc1));

    // Cloning increments count
    let rc2 = Rc::clone(&rc1);
    println!("\nAfter clone:");
    println!("  rc1 count: {}", Rc::strong_count(&rc1));
    println!("  rc2 count: {}", Rc::strong_count(&rc2));
    println!("  rc1 value: {}", rc1);
    println!("  rc2 value: {}", rc2);

    // Both point to same data
    println!("\nSame data? ptr equal: {}", Rc::ptr_eq(&rc1, &rc2));

    // Dropping decrements count
    drop(rc2);
    println!("\nAfter dropping rc2:");
    println!("  rc1 count: {}", Rc::strong_count(&rc1));

    // Rc with struct (shared ownership)
    struct SharedData {
        id: u32,
        name: String,
    }

    let data = Rc::new(SharedData {
        id: 1,
        name: String::from("Shared"),
    });

    let owner1 = Rc::clone(&data);
    let owner2 = Rc::clone(&data);
    println!("\nShared struct (count={}):", Rc::strong_count(&data));
    println!("  owner1: id={}, name={}", owner1.id, owner1.name);
    println!("  owner2: id={}, name={}", owner2.id, owner2.name);

    // Rc with Vec (shared collection)
    let shared_vec: Rc<Vec<String>> = Rc::new(vec![
        String::from("apple"),
        String::from("banana"),
    ]);

    let vec_ref1 = Rc::clone(&shared_vec);
    let vec_ref2 = Rc::clone(&shared_vec);
    println!("\nShared Vec (count={}): {:?}", Rc::strong_count(&shared_vec), vec_ref1);

    // Rc::try_unwrap - get inner value if count is 1
    let single_rc = Rc::new(String::from("Only me"));
    match Rc::try_unwrap(single_rc) {
        Ok(inner) => println!("\ntry_unwrap success: {}", inner),
        Err(rc) => println!("\ntry_unwrap failed, count={}", Rc::strong_count(&rc)),
    }

    // Strong vs Weak references
    let strong = Rc::new(String::from("Strong"));
    let weak: RcWeak<String> = Rc::downgrade(&strong);
    println!("\nStrong count: {}", Rc::strong_count(&strong));
    println!("Weak count: {}", Rc::weak_count(&strong));

    println!("\nKEY POINTS ABOUT Rc<T>:");
    println!("  • Multiple owners of same data");
    println!("  • NOT thread-safe!");
    println!("  • Reference count tracked automatically");
    println!("  • Data freed when last Rc is dropped");
    println!("  • Clone is cheap (just increments count)");
    println!("  • Use with RefCell for mutability");

    // ========================================================================
    // 8. Arc<T> - ATOMIC REFERENCE COUNTING (THREAD-SAFE)
    // ========================================================================
    section_header("8. Arc<T> - ATOMIC REFERENCE COUNTING");

    /*
    WHAT IS Arc<T>?
    - Like Rc but thread-safe
    - Uses atomic operations for reference counting
    - Can be shared across threads
    - Slightly slower than Rc due to atomic operations
    - Still immutable; use Mutex<T> inside for mutability
    */

    let shared_data = Arc::new(vec![1, 2, 3, 4, 5]);
    println!("Created Arc: {:?}", *shared_data);
    println!("Arc count: {}", Arc::strong_count(&shared_data));

    // Clone for each thread
    let mut handles = vec![];
    for i in 0..3 {
        let data_clone = Arc::clone(&shared_data);
        let handle = thread::spawn(move || {
            println!("  Thread {}: data={:?}, count={}", 
                i, *data_clone, Arc::strong_count(&data_clone));
        });
        handles.push(handle);
    }

    println!("Spawning threads with shared Arc...");
    for handle in handles {
        handle.join().unwrap();
    }
    println!("Final Arc count: {}", Arc::strong_count(&shared_data));

    // Arc with Mutex for shared mutable state
    println!("\n--- Arc<Mutex<T>> for shared mutable state ---");
    let counter = Arc::new(Mutex::new(0));
    let mut handles = vec![];

    for _ in 0..10 {
        let counter_clone = Arc::clone(&counter);
        handles.push(thread::spawn(move || {
            let mut num = counter_clone.lock().unwrap();
            *num += 1;
        }));
    }

    for handle in handles {
        handle.join().unwrap();
    }
    println!("Counter after 10 threads: {}", *counter.lock().unwrap());

    // Arc with RwLock for read-heavy workloads
    println!("\n--- Arc<RwLock<T>> for read-heavy workloads ---");
    let data = Arc::new(RwLock::new(HashMap::<String, i32>::new()));

    // Writer
    {
        let mut write = data.write().unwrap();
        write.insert("key1".to_string(), 100);
        write.insert("key2".to_string(), 200);
        println!("After write: {:?}", *write);
    }

    // Multiple readers (can read simultaneously)
    let mut handles = vec![];
    for i in 0..3 {
        let data_clone = Arc::clone(&data);
        handles.push(thread::spawn(move || {
            let read = data_clone.read().unwrap();
            println!("  Reader {} sees: key1={}", i, read.get("key1").unwrap());
        }));
    }
    for h in handles { h.join().unwrap(); }

    println!("\nKEY POINTS ABOUT Arc<T>:");
    println!("  • Thread-safe version of Rc");
    println!("  • Uses atomic operations (slight overhead)");
    println!("  • Combine with Mutex/RwLock for mutability");
    println!("  • Common pattern: Arc<Mutex<T>> or Arc<RwLock<T>>");
    println!("  • Essential for concurrent data sharing");

    // ========================================================================
    // 9. Cell<T> - COPY TYPES WITH INTERIOR MUTABILITY
    // ========================================================================
    section_header("9. Cell<T> - INTERIOR MUTABILITY FOR COPY TYPES");

    /*
    WHAT IS Cell<T>?
    - Provides interior mutability for Copy types
    - No runtime borrowing checks
    - Always copies values in and out
    - Cannot hold references (only Copy types)
    - get() copies the value, get_mut() requires &mut Cell
    */

    let cell = Cell::new(42);
    println!("Cell value: {}", cell.get());

    // Modify through shared reference!
    fn modify_cell(cell: &Cell<i32>) {
        cell.set(100);  // No &mut needed!
    }
    modify_cell(&cell);
    println!("After modify_cell: {}", cell.get());

    // replace() - returns old value
    let old = cell.replace(200);
    println!("replace() returned old: {}, new: {}", old, cell.get());

    // take() - replaces with Default and returns old
    let taken = cell.take();  // i32 default is 0
    println!("take() returned: {}, cell now: {}", taken, cell.get());

    // Cell with custom Copy type
    #[derive(Clone, Copy, Debug)]
    struct Color { r: u8, g: u8, b: u8 }

    let color_cell = Cell::new(Color { r: 255, g: 0, b: 0 });
    println!("\nColor cell: {:?}", color_cell.get());
    color_cell.set(Color { r: 0, g: 255, b: 0 });
    println!("Updated color: {:?}", color_cell.get());

    // Common use: interior counter
    struct CallbackCounter {
        count: Cell<usize>,
    }
    impl CallbackCounter {
        fn new() -> Self {
            CallbackCounter { count: Cell::new(0) }
        }
        fn increment(&self) {
            self.count.set(self.count.get() + 1);
        }
        fn get_count(&self) -> usize {
            self.count.get()
        }
    }

    let counter = CallbackCounter::new();
    counter.increment();
    counter.increment();
    counter.increment();
    println!("\nCallbackCounter: {}", counter.get_count());

    println!("\nKEY POINTS ABOUT Cell<T>:");
    println!("  • Interior mutability for Copy types only");
    println!("  • No runtime cost (no borrow checking)");
    println!("  • get() returns a copy, not a reference");
    println!("  • Cannot hold non-Copy types (no references)");
    println!("  • Use when you just need to "swap" values");

    // ========================================================================
    // 10. RefCell<T> - RUNTIME BORROW CHECKING
    // ========================================================================
    section_header("10. RefCell<T> - RUNTIME BORROW CHECKING");

    /*
    WHAT IS RefCell<T>?
    - Interior mutability for any type
    - Enforces borrowing rules at RUNTIME (panics if violated)
    - borrow() returns Ref<T> (like &T)
    - borrow_mut() returns RefMut<T> (like &mut T)
    - Multiple immutable borrows OR one mutable borrow
    - Used when compiler can't prove borrowing is safe
    */

    let ref_cell = RefCell::new(String::from("Hello"));
    println!("RefCell value: {}", ref_cell.borrow());

    // Immutable borrow
    let borrowed: Ref<String> = ref_cell.borrow();
    println!("Borrowed: {}", *borrowed);
    drop(borrowed);  // Must drop before mutable borrow

    // Mutable borrow (even though ref_cell is not mut!)
    let mut borrowed_mut: RefMut<String> = ref_cell.borrow_mut();
    borrowed_mut.push_str(", World!");
    drop(borrowed_mut);

    println!("After mutation: {}", ref_cell.borrow());

    // Runtime borrow checking - panic example (commented out)
    // let r1 = ref_cell.borrow();
    // let r2 = ref_cell.borrow_mut();  // PANIC! Already borrowed immutably

    // try_borrow() - returns Result instead of panicking
    let r1 = ref_cell.borrow();
    match ref_cell.try_borrow_mut() {
        Ok(_) => println!("\ntry_borrow_mut: Success"),
        Err(e) => println!("\ntry_borrow_mut: Failed - {}", e),
    }
    drop(r1);

    // RefCell with Rc - common pattern
    println!("\n--- Rc<RefCell<T>> Pattern ---");
    struct Node {
        value: i32,
        neighbors: RefCell<Vec<Rc<Node>>>,
    }

    let node1 = Rc::new(Node {
        value: 1,
        neighbors: RefCell::new(vec![]),
    });
    let node2 = Rc::new(Node {
        value: 2,
        neighbors: RefCell::new(vec![]),
    });
    let node3 = Rc::new(Node {
        value: 3,
        neighbors: RefCell::new(vec![]),
    });

    // Create bidirectional connections
    node1.neighbors.borrow_mut().push(Rc::clone(&node2));
    node2.neighbors.borrow_mut().push(Rc::clone(&node1));
    node2.neighbors.borrow_mut().push(Rc::clone(&node3));
    node3.neighbors.borrow_mut().push(Rc::clone(&node2));

    println!("Node {} neighbors: {:?}", 
        node1.value,
        node1.neighbors.borrow().iter().map(|n| n.value).collect::<Vec<_>>()
    );
    println!("Node {} neighbors: {:?}", 
        node2.value,
        node2.neighbors.borrow().iter().map(|n| n.value).collect::<Vec<_>>()
    );

    // borrow_state() - check current borrow status
    let cell = RefCell::new(0);
    println!("\nborrow_state() when idle: {:?}", cell.borrow_state()); // Unused

    let _r = cell.borrow();
    println!("borrow_state() when borrowed: {:?}", cell.borrow_state()); // Reading

    drop(_r);
    let _rm = cell.borrow_mut();
    println!("borrow_state() when borrow_mut: {:?}", cell.borrow_state()); // Writing

    println!("\nKEY POINTS ABOUT RefCell<T>:");
    println!("  • Interior mutability for any type");
    println!("  • Borrowing checked at runtime");
    println!("  • Panics on invalid borrow (use try_borrow)");
    println!("  • Common with Rc: Rc<RefCell<T>>");
    println!("  • Use when compiler can't verify safety");
    println!("  • Single-threaded only!");

    // ========================================================================
    // 11. Weak<T> - WEAK REFERENCES
    // ========================================================================
    section_header("11. Weak<T> - WEAK REFERENCES");

    /*
    WHAT IS Weak<T>?
    - Non-owning reference to Rc<T> or Arc<T>
    - Does NOT prevent data from being dropped
    - upgrade() returns Option<Rc<T>>/Option<Arc<T>>
    - Used to break reference cycles
    - Must check if data still exists before use
    */

    // Weak with Rc
    println!("--- Rc Weak ---");
    let strong = Rc::new(String::from("I'm strong"));
    let weak: RcWeak<String> = Rc::downgrade(&strong);

    println!("Strong count: {}", Rc::strong_count(&strong));
    println!("Weak count: {}", Rc::weak_count(&strong));

    // Upgrade weak to strong
    match weak.upgrade() {
        Some(s) => println!("Upgraded: {}", s),
        None => println!("Data already dropped"),
    }

    // Drop strong reference
    drop(strong);
    println!("\nAfter dropping strong:");
    match weak.upgrade() {
        Some(s) => println!("Upgraded: {}", s),
        None => println!("Data already dropped!"),
    }

    // Breaking reference cycles with Weak
    println!("\n--- Breaking Cycles with Weak ---");
    struct Child {
        name: String,
        parent: RefCell<RcWeak<Parent>>,
    }
    struct Parent {
        name: String,
        children: RefCell<Vec<Rc<Child>>>,
    }

    let parent = Rc::new(Parent {
        name: String::from("Parent"),
        children: RefCell::new(vec![]),
    });

    let child = Rc::new(Child {
        name: String::from("Child"),
        parent: RefCell::new(Rc::downgrade(&parent)),
    });

    parent.children.borrow_mut().push(Rc::clone(&child));

    println!("Parent: {}", parent.name);
    println!("Child: {}", child.name);
    
    // Child can access parent (if still alive)
    if let Some(p) = child.parent.borrow().upgrade() {
        println!("Child's parent: {}", p.name);
    }

    // When all Rc<Parent> dropped, parent is freed
    // Child's Weak<Parent> becomes invalid (no cycle!)

    // Weak with Arc (thread-safe)
    println!("\n--- Arc Weak ---");
    let arc_strong = Arc::new(String::from("Arc data"));
    let arc_weak: ArcWeak<String> = Arc::downgrade(&arc_strong);

    let handle = thread::spawn(move || {
        if let Some(data) = arc_weak.upgrade() {
            println!("Thread upgraded Arc Weak: {}", data);
        }
    });
    handle.join().unwrap();

    println!("\nKEY POINTS ABOUT Weak<T>:");
    println!("  • Does NOT keep data alive");
    println!("  • upgrade() to get Rc/Arc (returns Option)");
    println!("  • Essential for breaking reference cycles");
    println!("  • Use in parent-child relationships");
    println!("  • RcWeak for single-thread, ArcWeak for multi-thread");

    // ========================================================================
    // 12. Cow<T> - CLONE ON WRITE
    // ========================================================================
    section_header("12. Cow<T> - CLONE ON WRITE");

    /*
    WHAT IS Cow<T>?
    - Can hold either borrowed or owned data
    - "Clone on Write" - only clones when mutation needed
    - Useful for functions that may or may not modify input
    - Two variants: Cow::Borrowed(&T) or Cow::Owned(T)
    - Saves allocations when no modification needed
    */

    use std::borrow::Cow;

    // Cow with &str
    fn process_string(input: &str) -> Cow<str> {
        if input.contains("bad") {
            // Need to modify - returns Owned
            Cow::Owned(input.replace("bad", "good"))
        } else {
            // No modification needed - returns Borrowed
            Cow::Borrowed(input)
        }
    }

    let result1 = process_string("hello world");
    println!("No change: {:?} (is_borrowed={})", result1, matches!(result1, Cow::Borrowed(_)));

    let result2 = process_string("this is bad");
    println!("With change: {:?} (is_owned={})", result2, matches!(result2, Cow::Owned(_)));

    // Mutating Cow
    let mut cow: Cow<str> = Cow::Borrowed("hello");
    println!("\nInitial: {:?} (borrowed)", cow);

    cow.to_mut().push_str(" world");  // Triggers clone!
    println!("After to_mut: {:?} (owned)", cow);

    cow.to_mut().push_str("!");
    println!("After second to_mut: {:?} (still owned, no new clone)", cow);

    // Cow with slices
    let data = [1, 2, 3, 4, 5];
    let borrowed_slice: Cow<[i32]> = Cow::Borrowed(&data[..3]);
    println!("\nBorrowed slice: {:?}", borrowed_slice);

    let owned_slice: Cow<[i32]> = Cow::Owned(vec![10, 20, 30]);
    println!("Owned slice: {:?}", owned_slice);

    // Practical use case: function returning maybe-modified data
    fn ensure_ends_with_colon(s: &str) -> Cow<str> {
        if s.ends_with(':') {
            Cow::Borrowed(s)
        } else {
            Cow::Owned(format!("{}:", s))
        }
    }

    println!("\nensure_ends_with_colon('key:'): {:?}", ensure_ends_with_colon("key:"));
    println!("ensure_ends_with_colon('key'):  {:?}", ensure_ends_with_colon("key"));

    println!("\nKEY POINTS ABOUT Cow<T>:");
    println!("  • Defers cloning until mutation needed");
    println!("  • Can be borrowed or owned");
    println!("  • to_mut() clones if borrowed, returns &mut if owned");
    println!("  • Saves unnecessary allocations");
    println!("  • Common with &str and &[T]");

    // ========================================================================
    // 13. Mutex<T> - MUTUAL EXCLUSION LOCK
    // ========================================================================
    section_header("13. Mutex<T> - MUTUAL EXCLUSION LOCK");

    /*
    WHAT IS Mutex<T>?
    - Provides mutual exclusion (only one thread at a time)
    - lock() returns MutexGuard<T>
    - Guard implements Deref and DerefMut
    - Lock is released when guard is dropped
    - Can panic on "poisoning" if thread panicked while holding lock
    */

    let mutex = Mutex::new(0);
    println!("Created Mutex");

    // Basic locking
    {
        let mut guard = mutex.lock().unwrap();
        *guard = 42;
        println!("Inside lock: {}", *guard);
    } // Guard dropped here, lock released

    println!("After lock released: {}", *mutex.lock().unwrap());

    // Mutex with poison handling
    let mutex2 = Mutex::new(String::from("data"));
    // If a thread panics while holding the lock, it becomes "poisoned"
    match mutex2.lock() {
        Ok(guard) => println!("\nLock acquired: {}", *guard),
        Err(poisoned) => {
            println!("Lock poisoned, recovering data: {}", *poisoned.into_inner())
        }
    }

    // Multi-threaded example
    println!("\n--- Multi-threaded Mutex ---");
    let counter = Arc::new(Mutex::new(0));
    let mut handles = vec![];

    for i in 0..5 {
        let counter = Arc::clone(&counter);
        handles.push(thread::spawn(move || {
            let mut num = counter.lock().unwrap();
            *num += 1;
            println!("  Thread {} incremented to {}", i, *num);
        }));
    }

    for h in handles { h.join().unwrap(); }
    println!("Final value: {}", *counter.lock().unwrap());

    println!("\nKEY POINTS ABOUT Mutex<T>:");
    println!("  • Exclusive access (one thread at a time)");
    println!("  • Blocking - waits until lock available");
    println!("  • Lock automatically released on drop");
    println!("  • Can become poisoned on panic");
    println!("  • Use try_lock() for non-blocking");

    // ========================================================================
    // 14. RwLock<T> - READ-WRITE LOCK
    // ========================================================================
    section_header("14. RwLock<T> - READ-WRITE LOCK");

    /*
    WHAT IS RwLock<T>?
    - Multiple readers OR one writer (not both)
    - read() returns RwLockReadGuard
    - write() returns RwLockWriteGuard
    - Better than Mutex for read-heavy workloads
    - Writers are exclusive
    */

    let rwlock = RwLock::new(vec![1, 2, 3]);

    // Multiple readers (demonstrated in same thread with scoped access)
    {
        let r1 = rwlock.read().unwrap();
        let r2 = rwlock.read().unwrap();  // OK! Multiple readers
        println!("Reader 1: {:?}", *r1);
        println!("Reader 2: {:?}", *r2);
    }

    // Writer (exclusive)
    {
        let mut writer = rwlock.write().unwrap();
        writer.push(4);
        println!("After write: {:?}", *writer);
    }

    // Multi-threaded example
    println!("\n--- Multi-threaded RwLock ---");
    let data = Arc::new(RwLock::new(0));
    let mut handles = vec![];

    // Readers
    for i in 0..3 {
        let data = Arc::clone(&data);
        handles.push(thread::spawn(move || {
            let read = data.read().unwrap();
            println!("  Reader {} sees: {}", i, *read);
        }));
    }

    // Writer
    {
        let data = Arc::clone(&data);
        handles.push(thread::spawn(move || {
            let mut write = data.write().unwrap();
            *write += 100;
            println!("  Writer set to: {}", *write);
        }));
    }

    for h in handles { h.join().unwrap(); }

    println!("\nKEY POINTS ABOUT RwLock<T>:");
    println!("  • Multiple readers allowed simultaneously");
    println!("  • Writer has exclusive access");
    println!("  • Readers block while writer holds lock");
    println!("  • Writers block while any reader holds lock");
    println!("  • Use for read-heavy concurrent access");

    // ========================================================================
    // 15. OnceCell<T> AND OnceLock<T> - LAZY INITIALIZATION
    // ========================================================================
    section_header("15. OnceCell<T> AND OnceLock<T>");

    /*
    WHAT IS OnceCell<T>/OnceLock<T>?
    - Cell that can be set only once
    - OnceCell: single-threaded
    - OnceLock: thread-safe (uses std::sync)
    - Common pattern: lazy static initialization
    - get_or_init() for one-time initialization
    */

    // OnceCell (single-threaded)
    let cell = OnceCell::new();
    assert!(cell.get().is_none());
    
    cell.set(42).unwrap();
    assert_eq!(cell.get(), Some(&42));
    
    // set() fails after first set
    assert!(cell.set(100).is_err());
    println!("OnceCell value: {}", cell.get().unwrap());

    // get_or_init - initialize only once
    let cell2 = OnceCell::new();
    let value = cell2.get_or_init(|| {
        println!("  Initializing...");
        99
    });
    println!("get_or_init returned: {}", value);
    
    // Second call doesn't re-initialize
    let value2 = cell2.get_or_init(|| {
        println!("  This won't print!");
        0
    });
    println!("Second get_or_init: {}", value2);

    // OnceLock (thread-safe)
    println!("\n--- OnceLock (thread-safe) ---");
    use std::sync::OnceLock;
    
    static CONFIG: OnceLock<String> = OnceLock::new();
    
    fn get_config() -> &'static String {
        CONFIG.get_or_init(|| {
            String::from("Loaded configuration")
        })
    }
    
    println!("Config: {}", get_config());
    println!("Config (cached): {}", get_config());

    // lazy_static alternative with OnceLock
    fn expensive_computation() -> i32 {
        println!("  Computing...");
        12345
    }

    static RESULT: OnceLock<i32> = OnceLock::new();
    
    println!("Result: {}", RESULT.get_or_init(expensive_computation));
    println!("Result (cached): {}", RESULT.get_or_init(expensive_computation));

    println!("\nKEY POINTS ABOUT OnceCell/OnceLock:");
    println!("  • Set only once, panic on double-set");
    println!("  • get_or_init() for lazy initialization");
    println!("  • OnceCell: single-threaded");
    println!("  • OnceLock: thread-safe");
    println!("  • Replacement for lazy_static! macro");

    // ========================================================================
    // 16. NonNull<T> - NON-NULL RAW POINTER
    // ========================================================================
    section_header("16. NonNull<T> - NON-NULL RAW POINTER");

    /*
    WHAT IS NonNull<T>?
    - Raw pointer guaranteed to be non-null
    - Same size as *const T or *mut T
    - Enables null-pointer optimization
    - Used internally by smart pointers
    - Still unsafe to dereference
    */

    let value = 42;
    let ptr = &value as *const i32;

    // Create NonNull (unsafe - must guarantee non-null)
    let non_null = unsafe { NonNull::new_unchecked(ptr as *mut i32) };
    println!("NonNull pointer: {:p}", non_null);

    // Safe creation (returns Option)
    let maybe_non_null = NonNull::new(ptr as *mut i32);
    println!("NonNull::new result: {:?}", maybe_non_null);

    // Null case
    let null_result = NonNull::new(std::ptr::null_mut());
    println!("NonNull::new(null): {:?}", null_result);

    // NonNull is Copy
    let copy1 = non_null;
    let copy2 = non_null;
    println!("\nNonNull is Copy: both point to same: {:p}, {:p}", copy1, copy2);

    // Access as raw pointer
    unsafe {
        println!("Dereferenced: {}", *non_null.as_ptr());
    }

    println!("\nKEY POINTS ABOUT NonNull<T>:");
    println!("  • Guaranteed non-null (no Option overhead)");
    println!("  • Enables null-pointer optimization");
    println!("  • Used in smart pointer implementations");
    println!("  • Still unsafe to dereference");
    println!("  • Is Copy (unlike Box, Rc, etc.)");

    // ========================================================================
    // 17. Pin<T> - PINNING
    // ========================================================================
    section_header("17. Pin<P> - PINNING");

    /*
    WHAT IS Pin<P>?
    - Guarantees pointed data won't be moved in memory
    - Essential for self-referential types (like async futures)
    - Pin<&mut T> allows mutation but not move
    - Pin<Box<T>> owns and pins on heap
    - Unpin trait: most types are Unpin (safe to move)
    */

    // Most types are Unpin (safe to pin/unpin)
    let value = 42;
    let _pinned_ref: Pin<&i32> = Pin::new(&value);  // &i32 is Unpin

    // Pin<Box<T>> - owned pinned value on heap
    let pinned_box: Pin<Box<i32>> = Box::pin(100);
    println!("Pinned Box value: {}", *pinned_box);

    // Access inner value (if Unpin)
    println!("get_ref: {}", pinned_box.get_ref());

    // Self-referential struct (simplified example)
    use std::pin::Pin;
    use std::marker::PhantomPinned;

    struct SelfReferential {
        data: String,
        // In real code, this would be a pointer to `data`
        // pointer: *const String,
        _marker: PhantomPinned,  // Makes type !Unpin
    }

    // This type is !Unpin, so Pin protects it
    let _self_ref = Box::pin(SelfReferential {
        data: String::from("hello"),
        _marker: PhantomPinned,
    });
    println!("\nCreated !Unpin type with Box::pin");

    // Cannot get &mut to !Unpin type through Pin
    // let inner: &mut SelfReferential = _self_ref.get_mut(); // ERROR!
    
    // But can with unsafe (you must guarantee not to move it)
    unsafe {
        let inner: &mut SelfReferential = Pin::get_unchecked_mut(Pin::as_mut(&_self_ref));
        println!("Unsafe get_unchecked_mut: {}", inner.data);
    }

    println!("\nKEY POINTS ABOUT Pin<P>:");
    println!("  • Prevents moving the pointed-to value");
    println!("  • Essential for async/await (futures)");
    println!("  • Unpin types can be freely unpinned");
    println!("  • !Unpin types require Pin for safety");
    println!("  • PhantomPinned makes a type !Unpin");
    println!("  • Box::pin() is common way to pin");

    // ========================================================================
    // 18. FUNCTION POINTERS
    // ========================================================================
    section_header("18. FUNCTION POINTERS");

    /*
    FUNCTION POINTER TYPES:
    - fn(Type) -> Ret : Function pointer (thin pointer)
    - Fn(Type) -> Ret : Closure that captures by reference
    - FnMut(Type) -> Ret : Closure that captures by mutable reference
    - FnOnce(Type) -> Ret : Closure that captures by value (called once)
    - dyn Fn() : Trait object (fat pointer, double width)
    */

    // Function pointer (fn type)
    fn add(a: i32, b: i32) -> i32 { a + b }
    fn subtract(a: i32, b: i32) -> i32 { a - b }

    let math_fn: fn(i32, i32) -> i32 = add;
    println!("Function pointer (add): {}", math_fn(10, 5));

    let math_fn: fn(i32, i32) -> i32 = subtract;
    println!("Function pointer (sub): {}", math_fn(10, 5));

    // Array of function pointers
    let operations: [fn(i32, i32) -> i32; 2] = [add, subtract];
    println!("Operations array: [{}, {}]", operations[0](10, 5), operations[1](10, 5));

    // Fn closures (can be called multiple times, read captures)
    let multiplier = |x: i32| x * 2;
    println!("\nFn closure: {}", multiplier(21));

    // FnMut closure (can modify captures)
    let mut counter = 0;
    let mut increment = || {
        counter += 1;
        counter
    };
    println!("FnMut closure: {}", increment());
    println!("FnMut closure: {}", increment());

    // FnOnce closure (consumes captured values)
    let text = String::from("Hello");
    let consume = || {
        text  // moves text into closure
    };
    let result = consume();
    println!("\nFnOnce closure consumed: {}", result);
    // consume(); // ERROR! Can only call once

    // Boxing closures (dyn Fn trait object)
    let boxed_closure: Box<dyn Fn(i32) -> i32> = Box::new(|x| x * 10);
    println!("\nBoxed dyn Fn: {}", boxed_closure(5));

    // Function pointer as parameter
    fn apply(f: fn(i32) -> i32, x: i32) -> i32 {
        f(x)
    }
    fn double(x: i32) -> i32 { x * 2 }
    println!("apply(double, 5): {}", apply(double, 5));

    // Generic over closure types
    fn apply_generic<F: Fn(i32) -> i32>(f: F, x: i32) -> i32 {
        f(x)
    }
    println!("apply_generic(closure, 5): {}", apply_generic(|x| x + 100, 5));

    println!("\nKEY POINTS ABOUT FUNCTION POINTERS:");
    println!("  • fn type: thin pointer to function");
    println!("  • Fn/FnMut/FnOnce: closure traits");
    println!("  • dyn Fn: fat pointer (data + vtable)");
    println!("  • Box<dyn Fn>: heap-allocated closure");
    println!("  • fn pointers are Copy");

    // ========================================================================
    // 19. *const c_void AND *mut c_void - GENERIC RAW POINTERS
    // ========================================================================
    section_header("19. *const c_void AND *mut c_void");

    /*
    WHAT IS c_void?
    - Equivalent to C's void*
    - Used for FFI when type is unknown
    - Must cast to concrete type before use
    - Size: same as pointer (4 or 8 bytes)
    */

    let integer: i32 = 42;
    let float: f64 = 3.14;

    // Cast to void pointer
    let void_ptr: *const c_void = &integer as *const i32 as *const c_void;
    println!("i32 as c_void: {:p}", void_ptr);

    // Cast back
    let back_to_i32: *const i32 = void_ptr as *const i32;
    unsafe {
        println!("Cast back to i32: {}", *back_to_i32);
    }

    // Another example
    let void_from_float: *const c_void = &float as *const f64 as *const c_void;
    let back_to_f64: *const f64 = void_from_float as *const f64;
    unsafe {
        println!("f64 through c_void: {}", *back_to_f64);
    }

    // Use case: generic C function
    println!("\nCommon in FFI:");
    println!("  void* malloc(size_t size);");
    println!("  void free(void* ptr);");
    println!("  In Rust: *mut c_void");

    // ========================================================================
    // 20. POINTER COMPARISON AND CONVERSIONS
    // ========================================================================
    section_header("20. POINTER COMPARISON AND CONVERSIONS");

    let a = 10;
    let b = 20;

    let ptr_a = &a as *const i32;
    let ptr_b = &b as *const i32;
    let ptr_a2 = &a as *const i32;

    // Pointer comparison
    println!("ptr_a == ptr_b: {}", ptr_a == ptr_b);
    println!("ptr_a == ptr_a2: {}", ptr_a == ptr_a2);

    // Pointer ordering
    println!("ptr_a < ptr_b: {}", ptr_a < ptr_b);

    // Pointer to usize (address as number)
    let addr: usize = ptr_a as usize;
    println!("\nPointer as usize: {}", addr);

    // usize to pointer (unsafe!)
    let reconstructed: *const i32 = addr as *const i32;
    unsafe {
        println!("Reconstructed pointer value: {}", *reconstructed);
    }

    // Conversion table
    println!("\n--- CONVERSION SUMMARY ---");
    println!("&T        -> *const T  (safe, via as)");
    println!("&mut T    -> *mut T    (safe, via as)");
    println!("*const T  -> *mut T    (unsafe to write)");
    println!("*mut T    -> *const T  (safe, implicit)");
    println!("*const T  -> usize     (safe, via as)");
    println!("usize     -> *const T  (unsafe to deref)");
    println!("Box<T>    -> *mut T    (via Box::into_raw)");
    println!("*mut T    -> Box<T>    (via Box::from_raw, unsafe)");
    println!("Rc<T>     -> *const T  (via Rc::as_ptr)");
    println!("&T        -> NonNull<T> (unsafe new_unchecked)");

    // Box <-> Raw pointer roundtrip
    let boxed = Box::new(String::from("Roundtrip"));
    let raw = Box::into_raw(boxed);
    println!("\nBox to raw: {:p}", raw);
    
    // Reconstruct Box (unsafe! must only do this once!)
    let reconstructed_box = unsafe { Box::from_raw(raw) };
    println!("Raw to Box: {}", reconstructed_box);
    // reconstructed_box is dropped here, freeing the memory

    // ========================================================================
    // SUMMARY TABLE
    // ========================================================================
    section_header("SUMMARY TABLE - ALL POINTER TYPES");

    println!("┌──────────────┬─────────┬───────────┬──────────────┬─────────────────┐");
    println!("│ Type         │ Size    │ Null?     │ Thread-Safe? │ Primary Use     │");
    println!("├──────────────┼─────────┼───────────┼──────────────┼─────────────────┤");
    println!("│ &T           │ 1 ptr   │ No        │ Yes*         │ Borrowing       │");
    println!("│ &mut T       │ 1 ptr   │ No        │ Yes*         │ Mutable borrow  │");
    println!("│ *const T     │ 1 ptr   │ Yes       │ Yes          │ FFI, unsafe     │");
    println!("│ *mut T       │ 1 ptr   │ Yes       │ Yes          │ FFI, unsafe     │");
    println!("│ Box<T>       │ 1 ptr   │ No        │ Yes          │ Heap alloc      │");
    println!("│ Rc<T>        │ 2 ptrs  │ No        │ No           │ Shared ownership│");
    println!("│ Arc<T>       │ 2 ptrs  │ No        │ Yes          │ Threaded shared │");
    println!("│ RefCell<T>   │ 1 ptr+  │ No        │ No           │ Interior mut    │");
    println!("│ Cell<T>      │ 1 ptr   │ No        │ No           │ Copy inter. mut │");
    println!("│ Weak<T>      │ 2 ptrs  │ Yes†      │ Varies       │ Break cycles    │");
    println!("│ Cow<T>       │ varies  │ No        │ Yes*         │ Lazy cloning    │");
    println!("│ Mutex<T>     │ 1 ptr+  │ No        │ Yes          │ Thread safety   │");
    println!("│ RwLock<T>    │ 1 ptr+  │ No        │ Yes          │ Read-write lock │");
    println!("│ OnceCell<T>  │ 1 ptr+  │ No        │ No           │ Lazy init (ST)  │");
    println!("│ OnceLock<T>  │ 1 ptr+  │ No        │ Yes          │ Lazy init (MT)  │");
    println!("│ NonNull<T>   │ 1 ptr   │ No        │ Yes          │ Opt. null check │");
    println!("│ Pin<P>       │ = P     │ = P       │ = P          │ Self-referential│");
    println!("│ fn()         │ 1 ptr   │ No        │ Yes          │ Function ptr    │");
    println!("│ dyn Fn()     │ 2 ptrs  │ No        │ Yes*         │ Closure trait   │");
    println!("│ *const c_void│ 1 ptr   │ Yes       │ Yes          │ FFI void*       │");
    println!("└──────────────┴─────────┴───────────┴──────────────┴─────────────────┘");
    println!("* If T is Send+Sync    † upgrade() returns Option (may be None)");

    println!("\n{}", "=".repeat(75));
    println!("                      END OF GUIDE");
    println!("{}", "=".repeat(75));
}

// Helper function for mutable reference example
fn modify_age(person: &mut Person) {
    person.age += 1;
}

struct Person {
    name: String,
    age: u32,
}

// Helper function to print tree
fn print_tree(node: &TreeNode, indent: usize) {
    let prefix = "  ".repeat(indent);
    println!("{}Node({})", prefix, node.value);
    if let Some(ref left) = node.left {
        print_tree(left, indent + 1);
    }
    if let Some(ref right) = node.right {
        print_tree(right, indent + 1);
    }
}

// TreeNode defined earlier in the Box section
struct TreeNode {
    value: i32,
    left: Option<Box<TreeNode>>,
    right: Option<Box<TreeNode>>,
}

// Helper function to print section headers
fn section_header(title: &str) {
    println!("\n{}", "─".repeat(75));
    println!("  {}", title);
    println!("{}", "─".repeat(75));
}