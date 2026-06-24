import os

# Define the Cargo project structure
PROJECT_NAME = "rust_pointer_examples"
EXAMPLES_DIR = os.path.join(PROJECT_NAME, "examples")
SRC_DIR = os.path.join(PROJECT_NAME, "src")

# Dictionary of all pointer examples: {filename: rust_code}
RUST_EXAMPLES = {
    "01_immutable_ref.rs": """\
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
""",

    "02_mutable_ref.rs": """\
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
""",

    "03_raw_const_ptr.rs": """\
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
""",

    "04_raw_mut_ptr.rs": """\
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
""",

    "05_box.rs": """\
// ============================================================================
// 5. Box<T> - HEAP ALLOCATION
// ============================================================================
// Box<T> is a smart pointer that puts data on the HEAP instead of the stack.
// - It has single ownership (like a regular variable, just on the heap).
// - It automatically frees memory when it goes out of scope (Drop trait).
// - It allows for recursive types (a struct containing itself).
// - It enables dynamic dispatch for trait objects (dyn Trait).

fn main() {
    // Basic heap allocation
    let boxed_num = Box::new(42);
    println!("Boxed number: {}", boxed_num);
    println!("Size of Box pointer on stack: {} bytes", std::mem::size_of_val(&boxed_num));

    // Mutable Box
    let mut boxed_str = Box::new(String::from("Hello"));
    boxed_str.push_str(", Heap!");
    println!("Mutable Box: {}", boxed_str);

    // RECURSIVE TYPES (Impossible without Box because compiler can't know size)
    enum List {
        Cons(i32, Box<List>),
        Nil,
    }
    let recursive_list = List::Cons(1, 
        Box::new(List::Cons(2, 
            Box::new(List::Cons(3, 
                Box::new(List::Nil))))));
    println!("Created recursive list successfully!");

    // DYNAMIC DISPATCH (Trait Objects)
    trait Animal { fn speak(&self); }
    struct Dog;
    struct Cat;
    impl Animal for Dog { fn speak(&self) { println!("  Woof!"); } }
    impl Animal for Cat { fn speak(&self) { println!("  Meow!"); } }

    // Vec of animals with different sizes, erased to a fat pointer (Box<dyn Animal>)
    let animals: Vec<Box<dyn Animal>> = vec![Box::new(Dog), Box::new(Cat)];
    for animal in animals {
        animal.speak();
    }
}
""",

    "06_rc.rs": """\
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
    println!("\nGraph branches share node: {} and {}", branch1, branch2);
}
""",

    "07_arc.rs": """\
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
""",

    "08_cell.rs": """\
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
""",

    "09_refcell.rs": """\
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
""",

    "10_weak.rs": """\
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
""",

    "11_cow.rs": """\
// ============================================================================
// 11. Cow<T> - CLONE ON WRITE
// ============================================================================
// Cow is an enum that can hold either borrowed data OR owned data.
// - Cow::Borrowed(&T) - just a reference, no allocation.
// - Cow::Owned(T) - owns the data.
// - If you need to modify a Borrowed variant, it automatically clones it into an Owned variant.
// - Perfect for functions that return modified strings but want to avoid allocations if unmodified.

use std::borrow::Cow;

fn main() {
    // A function that might need to modify a string
    fn ensure_hebrew(s: &str) -> Cow<str> {
        if s.contains("שלום") {
            // Already Hebrew, return a Borrowed reference (zero allocation)
            Cow::Borrowed(s)
        } else {
            // Needs modification, return an Owned String (allocates)
            Cow::Owned(format!("שלום {}", s))
        }
    }

    let hebrew_text = "שלום עולם";
    let result1 = ensure_hebrew(hebrew_text);
    println!("Text 1: {}, is_borrowed: {}", result1, matches!(result1, Cow::Borrowed(_)));

    let english_text = "World";
    let result2 = ensure_hebrew(english_text);
    println!("Text 2: {}, is_owned: {}", result2, matches!(result2, Cow::Owned(_)));

    // to_mut() triggers clone only once
    let mut cow = Cow::Borrowed("hello");
    cow.to_mut().push_str(" world"); // Clones here!
    cow.to_mut().push_str("!");      // Does NOT clone again, already owned
    println!("Mutated Cow: {}", cow);
}
""",

    "12_mutex.rs": """\
// ============================================================================
// 12. Mutex<T> - MUTUAL EXCLUSION LOCK
// ============================================================================
// Mutex ensures only ONE thread can access the data at a time.
// - .lock() blocks the thread until it gets access, returning a MutexGuard.
// - The guard implements DerefMut, so you can use `*` or just treat it as the inner type.
// - When the guard goes out of scope, the lock is automatically released.
// - Standard pattern: Arc<Mutex<T>> for sharing mutable data across threads.

use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    // Single threaded Mutex
    let m = Mutex::new(5);
    {
        let mut guard = m.lock().unwrap();
        *guard += 1;
        println!("Inside lock: {}", *guard);
    } // Lock released here
    
    println!("Outside lock: {}", m.lock().unwrap());

    // Multi-threaded pattern
    let counter = Arc::new(Mutex::new(0));
    let mut handles = vec![];

    for _ in 0..10 {
        let counter = Arc::clone(&counter);
        handles.push(thread::spawn(move || {
            let mut num = counter.lock().unwrap();
            *num += 1; // Safe mutation!
        }));
    }

    for handle in handles {
        handle.join().unwrap();
    }

    println!("Final counter: {}", *counter.lock().unwrap());
}
""",

    "13_rwlock.rs": """\
// ============================================================================
// 13. RwLock<T> - READ-WRITE LOCK
// ============================================================================
// RwLock allows multiple readers AT THE SAME TIME, but only one writer.
// - .read() returns RwLockReadGuard. Blocks if a writer is active.
// - .write() returns RwLockWriteGuard. Blocks until all readers/writers are done.
// - Better performance than Mutex for read-heavy workloads.

use std::sync::{Arc, RwLock};
use std::thread;

fn main() {
    let data = Arc::new(RwLock::new(vec![1, 2, 3]));

    let mut handles = vec![];

    // Spawn 3 readers
    for i in 0..3 {
        let data = Arc::clone(&data);
        handles.push(thread::spawn(move || {
            let read_guard = data.read().unwrap();
            // Multiple threads can hold this read lock simultaneously!
            println!("Reader {} sees: {:?}", i, *read_guard);
        }));
    }

    // Spawn 1 writer
    {
        let data = Arc::clone(&data);
        handles.push(thread::spawn(move || {
            let mut write_guard = data.write().unwrap();
            // Exclusive access: no readers can read while this is active
            write_guard.push(4);
            println!("Writer pushed 4!");
        }));
    }

    for handle in handles {
        handle.join().unwrap();
    }
    println!("Final data: {:?}", *data.read().unwrap());
}
""",

    "14_oncecell.rs": """\
// ============================================================================
// 14. OnceCell<T> / OnceLock<T> - LAZY INITIALIZATION
// ============================================================================
// OnceCell/OnceLock allow you to initialize a value exactly ONCE.
// - OnceCell is for single-threaded contexts.
// - OnceLock is for multi-threaded contexts (replaces lazy_static!).
// - .get_or_init() takes a closure. If empty, runs closure and stores result.
// - Subsequent calls return the cached value without running the closure again.

use std::cell::OnceCell;
use std::sync::OnceLock;

fn main() {
    // OnceCell (Single Threaded)
    let cell = OnceCell::new();
    assert!(cell.get().is_none());
    
    let value = cell.get_or_init(|| {
        println!("Initializing expensive computation...");
        42
    });
    
    println!("Value: {}", value);
    
    // Second call does NOT print "Initializing..."
    let _ = cell.get_or_init(|| {
        println!("This will NOT print");
        99
    });

    // OnceLock (Multi-threaded safe, often used as static global)
    static GLOBAL_CONFIG: OnceLock<String> = OnceLock::new();
    
    let config = GLOBAL_CONFIG.get_or_init(|| {
        String::from("Loaded from disk/config")
    });
    
    println!("Global Config: {}", config);
}
""",

    "15_nonnull.rs": """\
// ============================================================================
// 15. NonNull<T> - GUARANTEED NON-NULL RAW POINTER
// ============================================================================
// NonNull<T> is a raw pointer that is guaranteed by the type system to NOT be null.
// - It is the same size as a raw pointer.
// - Why use it? It enables the "null pointer optimization" (e.g., Option<Box<T>> 
//   takes up the exact same space as Box<T> because the null state is stored in the pointer).
// - Creating it is unsafe because you must guarantee it's not null.
// - Used extensively inside smart pointer implementations.

use std::ptr::NonNull;

fn main() {
    let value = 100;
    let raw_ptr = &value as *const i32;

    // Safe creation (returns Option, handles nulls)
    let maybe_nonnull = NonNull::new(raw_ptr as *mut i32);
    println!("Safe NonNull: {:?}", maybe_nonnull);

    // Unsafe creation (you guarantee it's not null)
    let non_null = unsafe { NonNull::new_unchecked(raw_ptr as *mut i32) };
    
    // NonNull is Copy!
    let copy1 = non_null;
    let copy2 = non_null;
    println!("NonNull is Copy: {:p}, {:p}", copy1, copy2);

    // Use in Option (Demonstrating Null Pointer Optimization concept)
    // Option<NonNull<i32>> takes exactly 8 bytes (same as a pointer)
    // Option<*mut i32> takes 16 bytes (pointer + discriminant)
    println!("Size of Option<NonNull<i32>>: {} bytes", std::mem::size_of::<Option<NonNull<i32>>>());
    println!("Size of Option<*mut i32>: {} bytes", std::mem::size_of::<Option<*mut i32>>());
}
""",

    "16_pin.rs": """\
// ============================================================================
// 16. Pin<P> - PINNING (Preventing Moves)
// ============================================================================
// Pin guarantees that the data pointed to will not be moved in memory.
// - Crucial for async/await (Futures) because they contain self-referential pointers.
// - Most types are Unpin (safe to move). Pin<Unpin> does nothing special.
// - Types with PhantomPinned are !Unpin. Pin prevents you from getting &mut to them.
// - Box::pin() is the standard way to pin something to the heap.

use std::pin::Pin;
use std::marker::PhantomPinned;

// A self-referential struct (simplified)
struct SelfRef {
    data: String,
    // In reality, this would point to `data`. If struct moves, this pointer breaks!
    _marker: PhantomPinned, // Makes this struct !Unpin
}

fn main() {
    // Pinning an Unpin type (like i32) - trivial
    let mut unpinned_num = 42;
    let _pinned_num = Pin::new(&mut unpinned_num); // Can still actually move unpinned_num

    // Pinning a !Unpin type using Box::pin
    let pinned_struct = Box::pin(SelfRef {
        data: String::from("Hello"),
        _marker: PhantomPinned,
    });

    println!("Pinned struct data: {}", pinned_struct.data);

    // You CANNOT do this:
    // let mut_ref: &mut SelfRef = &mut *pinned_struct; // ERROR!

    // You MUST use unsafe and promise not to move it:
    unsafe {
        let inner: &mut SelfRef = Pin::get_unchecked_mut(pinned_struct.as_mut());
        inner.data.push_str(" World");
        println!("Mutated pinned data: {}", inner.data);
    }
}
""",

    "17_fn_pointers.rs": """\
// ============================================================================
// 17. FUNCTION POINTERS & CLOSURES
// ============================================================================
// Rust has distinct types for functions and closures:
// - `fn(Type) -> Type`: Plain function pointer (thin pointer, Copy).
// - `Fn`, `FnMut`, `FnOnce`: Traits implemented by closures.
// - `dyn Fn()`: Trait object (fat pointer, used for dynamic dispatch).

fn main() {
    // 1. Function Pointers (fn)
    fn add(a: i32, b: i32) -> i32 { a + b }
    fn sub(a: i32, b: i32) -> i32 { a - b }
    
    let math_op: fn(i32, i32) -> i32 = add;
    println!("Function pointer (add): {}", math_op(10, 5));
    
    // You can store them in arrays/vecs because they are just pointers
    let ops: Vec<fn(i32, i32) -> i32> = vec![add, sub];
    println!("Function pointer vec: {}", ops[1](10, 5));

    // 2. Closures
    let x = 10;
    
    // Fn: captures by reference (immutable). Can be called multiple times.
    let fn_closure = |y| x + y;
    println!("Fn closure: {}", fn_closure(5));

    // FnMut: captures by mutable reference. Can modify environment.
    let mut counter = 0;
    let mut fnmut_closure = || {
        counter += 1;
        counter
    };
    fnmut_closure();
    println!("FnMut closure: {}", fnmut_closure());

    // FnOnce: captures by value (takes ownership). Can only be called ONCE.
    let text = String::from("Owned");
    let fnonce_closure = || {
        println!("FnOnce consumed: {}", text);
    };
    fnonce_closure();
    // fnonce_closure(); // ERROR! Already consumed.

    // 3. Boxed Closures (Dynamic Dispatch)
    // When you don't know the exact closure type at compile time
    let boxed: Box<dyn Fn(i32) -> i32> = Box::new(|x| x * 2);
    println!("Boxed dyn Fn: {}", boxed(10));
}
""",

    "18_c_void.rs": """\
// ============================================================================
// 18. *const c_void AND *mut c_void
// ============================================================================
// `c_void` is Rust's equivalent to C's `void*`.
// - It represents a generic, untyped pointer.
// - Used heavily in FFI when C code returns a void* that you must cast back 
//   to a specific Rust type later.
// - Size is identical to a standard pointer.

use std::ffi::c_void;

fn main() {
    let my_i32: i32 = 42;
    let my_f64: f64 = 3.14;

    // Cast Rust pointers to c_void (safe to cast)
    let void_i32: *const c_void = &my_i32 as *const i32 as *const c_void;
    let void_f64: *const c_void = &my_f64 as *const f64 as *const c_void;

    println!("i32 as c_void address: {:p}", void_i32);
    println!("f64 as c_void address: {:p}", void_f64);

    // Cast back from c_void to concrete type (unsafe to deref)
    unsafe {
        // You MUST know the correct original type!
        let back_to_i32: *const i32 = void_i32 as *const i32;
        println!("Recovered i32: {}", *back_to_i32);

        let back_to_f64: *const f64 = void_f64 as *const f64;
        println!("Recovered f64: {}", *back_to_f64);
    }

    // Simulating a C malloc/free pattern
    println!("\nSimulating C malloc:");
    unsafe {
        // malloc returns *mut c_void
        let ptr: *mut c_void = libc::malloc(std::mem::size_of::<i32>());
        if !ptr.is_null() {
            // Cast to typed pointer and write
            let typed_ptr = ptr as *mut i32;
            *typed_ptr = 999;
            println!("Wrote to malloc'd memory: {}", *typed_ptr);
            
            // free expects *mut c_void
            libc::free(ptr);
            println!("Freed memory.");
        }
    }
}
// Note: To run the libc example, add `libc = "0.2"` to Cargo.toml
""",

    "19_conversions.rs": """\
// ============================================================================
// 19. POINTER CONVERSIONS & INTERFACES
// ============================================================================
// Understanding how to convert between Rust's pointer types safely and unsafely.

use std::rc::Rc;

fn main() {
    let mut value = 42;
    let boxed = Box::new(value);

    // 1. &T <-> *const T  (Safe to cast)
    let r: &i32 = &value;
    let p: *const i32 = r as *const i32;
    println!("&T to *const T: {:p}", p);

    // 2. &mut T <-> *mut T (Safe to cast)
    let rm: &mut i32 = &mut value;
    let pm: *mut i32 = rm as *mut i32;
    
    // 3. *mut T -> *const T (Safe, implicit)
    let p_const: *const i32 = pm;
    println!("*mut T to *const T: {:p}", p_const);

    // 4. Pointer to usize (Get raw address)
    let addr: usize = pm as usize;
    println!("Pointer as usize address: {}", addr);

    // 5. Box<T> <-> *mut T (Roundtrip)
    let raw_from_box = Box::into_raw(boxed); // Consumes the Box, returns *mut T
    println!("Box into *mut T: {:p}", raw_from_box);
    
    // WARNING: raw_from_box is now fully manual. If we don't reconstruct it, it leaks.
    let reconstructed_box = unsafe { Box::from_raw(raw_from_box) };
    println!("*mut T back to Box: {}", reconstructed_box);
    // reconstructed_box drops normally here, freeing memory.

    // 6. Rc<T> -> *const T
    let rc = Rc::new(String::from("Hello Rc"));
    let rc_ptr: *const String = Rc::as_ptr(&rc);
    println!("\nRc as *const T: {:p}", rc_ptr);
    unsafe {
        println!("Dereferenced Rc ptr: {}", *rc_ptr);
    }
}
"""
}

def main():
    # Create project directories
    os.makedirs(EXAMPLES_DIR, exist_ok=True)
    os.makedirs(SRC_DIR, exist_ok=True)

    # 1. Generate Cargo.toml
    cargo_toml_content = """\
[package]
name = "rust_pointer_examples"
version = "0.1.0"
edition = "2021"

# Uncomment the line below to run the c_void example (example 18)
# [dependencies]
# libc = "0.2"
"""
    with open(os.path.join(PROJECT_NAME, "Cargo.toml"), "w") as f:
        f.write(cargo_toml_content)
    print(f"Generated: {PROJECT_NAME}/Cargo.toml")

    # 2. Generate dummy src/main.rs so Cargo doesn't complain
    with open(os.path.join(SRC_DIR, "main.rs"), "w") as f:
        f.write('// Run examples using: cargo run --example <name>\nfn main() {}\n')
    print(f"Generated: {SRC_DIR}/main.rs")

    # 3. Generate all example files
    for filename, code in RUST_EXAMPLES.items():
        filepath = os.path.join(EXAMPLES_DIR, filename)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"Generated: {filepath}")

    print("\n" + "="*50)
    print("SUCCESS! Project generated.")
    print("="*50)
    print(f"cd into '{PROJECT_NAME}' and run an example:")
    print(f"  cd {PROJECT_NAME}")
    print(f"  cargo run --example 05_box")
    print(f"\nTo run all examples sequentially:")
    print(f"  for f in examples/*.rs; do cargo run --example $(basename $f .rs); done")

if __name__ == "__main__":
    main()