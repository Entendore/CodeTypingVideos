//! # Rust Pointers: A Comprehensive Guide
//! 
//! This program covers:
//! - References (borrowed pointers): &T and &mut T
//! - Raw pointers: *const T and *mut T
//! - Smart pointers: Box<T>, Rc<T>, Arc<T>, RefCell<T>, Cow<T>
//! - Common pitfalls and best practices

use std::cell::RefCell;
use std::rc::{Rc, Weak};
use std::sync::{Arc, Mutex};
use std::borrow::Cow;
use std::ptr::{self, NonNull};

// ============================================================================
// SECTION 1: REFERENCES (BORROWED POINTERS)
// ============================================================================

/// Demonstrates PROPER use of references
mod reference_dos {
    /// DO: Use immutable references freely - multiple readers are allowed
    pub fn multiple_readers() {
        let data = String::from("Hello, Rust!");
        
        // Multiple immutable references are perfectly fine
        let ref1 = &data;
        let ref2 = &data;
        let ref3 = &data;
        
        println!("Multiple readers: {} {} {}", ref1, ref2, ref3);
    }
    
    /// DO: Limit mutable references to one at a time - this prevents data races
    pub fn single_writer() {
        let mut data = String::from("Hello");
        
        {
            let writer = &mut data;
            writer.push_str(", World!");
            // No other references to 'data' can exist here
        } // writer goes out of scope here
        
        // Now we can create new references
        let reader = &data;
        println!("After mutation: {}", reader);
    }
    
    /// DO: Use lifetime annotations for functions returning references
    pub fn proper_lifetimes<'a>(input: &'a str) -> &'a str {
        // Lifetime 'a ensures the returned reference lives as long as the input
        input.trim()
    }
    
    /// DO: Use references for function parameters when you don't need ownership
    pub fn efficient_parameter_passing(data: &[u8]) -> usize {
        data.len() // No allocation, just borrowing
    }
    
    /// DO: Use reborrowing to temporarily give up access
    pub fn reborrowing_example() {
        let mut value = 42;
        let reference = &mut value;
        
        // Reborrow: we temporarily create a new reference from our mutable reference
        let inner_ref: &i32 = &*reference;
        println!("Reborrowed value: {}", inner_ref);
        
        // We can still use 'reference' after the reborrow ends
        *reference += 1;
        println!("After modification: {}", reference);
    }
    
    /// DO: Use pattern matching to destructure references
    pub fn reference_pattern_matching() {
        let tuple_ref = &(1, "hello", 3.14);
        
        // Destructure through the reference
        let (a, b, c) = tuple_ref;
        println!("Destructured: {}, {}, {}", a, b, c);
        
        // Or match with ref keyword
        let value = 42;
        if let Some(ref x) = Some(&value) {
            println!("Matched with ref: {}", x);
        }
    }
}

/// Demonstrates IMPROPER use of references (these would be compile errors)
mod reference_donts {
    /// DON'T: Try to have mutable and immutable references simultaneously
    /// 
    /// This code would NOT compile - uncomment to see the error
    pub fn simultaneous_borrows() {
        let mut data = String::from("Hello");
        
        let immutable_ref = &data;
        // let mutable_ref = &mut data; // ERROR: cannot borrow as mutable because it's also borrowed as immutable
        
        println!("Only immutable: {}", immutable_ref);
        
        // Fix: Wait for immutable reference to be no longer used
        // let mutable_ref = &mut data; // This would work here
    }
    
    /// DON'T: Return references to local variables
    /// 
    /// This code would NOT compile - uncomment to see the error
    pub fn dangling_reference<'a>() -> &'a String {
        // let local = String::from("temporary");
        // &local // ERROR: 'local' does not live long enough
        
        // Fix: Return owned value or use static lifetime
        // "static string".to_string() // Returns owned String
        static STATIC_STRING: &str = "I live forever";
        STATIC_STRING // This works because it's static
    }
    
    /// DON'T: Create self-referential structs with plain references
    /// 
    /// This pattern is problematic because moving the struct invalidates internal references
    pub fn self_referential_struct_problem() {
        // This struct definition would be problematic:
        // struct SelfReferential {
        //     data: String,
        //     pointer: &str, // Points to data field - DANGEROUS!
        // }
        
        // Fix: Use indices or smart pointers instead
        struct SafeSelfReferential {
            data: String,
            slice_range: std::ops::Range<usize>, // Use range instead of pointer
        }
        
        let safe = SafeSelfReferential {
            data: "Hello, World!".to_string(),
            slice_range: 7..12,
        };
        println!("Safe slice: {}", &safe.data[safe.slice_range.clone()]);
    }
    
    /// DON'T: Forget that references are implicitly reborrowed
    pub fn reborrow_gotcha() {
        let mut x = 5;
        let r = &mut x;
        
        // This passes a reborrow, r is still usable
        takes_mut_ref(r);
        
        // r is still valid here because we only reborrowed
        *r = 10;
        println!("r is still valid: {}", r);
    }
    
    fn takes_mut_ref(_: &mut i32) {}
}

// ============================================================================
// SECTION 2: RAW POINTERS
// ============================================================================

/// Demonstrates PROPER use of raw pointers
mod raw_pointer_dos {
    use std::ptr;
    
    /// DO: Use raw pointers when interfacing with C code (FFI)
    pub fn ffi_safe_usage() {
        let data: i32 = 42;
        
        // Create raw pointers - this is always safe
        let raw_const: *const i32 = &data;
        let raw_mut: *mut i32 = &data as *mut i32;
        
        // Reading/writing requires unsafe block
        unsafe {
            println!("FFI-style read: {}", *raw_const);
            // *raw_mut = 100; // Would be UB if data wasn't actually mutable
        }
    }
    
    /// DO: Use NonNull for guaranteed non-null raw pointers
    pub fn nonnull_usage() {
        let data = 42;
        
        // NonNull is a pointer that's guaranteed to be non-null
        let non_null = unsafe { NonNull::new_unchecked(&data as *const i32) };
        
        if let Some(ptr) = non_null {
            unsafe {
                println!("NonNull points to: {}", *ptr.as_ptr());
            }
        }
    }
    
    /// DO: Check for null before dereferencing
    pub fn safe_null_check(ptr: *const i32) -> Option<i32> {
        if ptr.is_null() {
            None
        } else {
            // Still need unsafe to dereference
            unsafe { Some(*ptr) }
        }
    }
    
    /// DO: Use pointer methods that don't require unsafe
    pub fn safe_pointer_operations() {
        let arr = [1, 2, 3, 4, 5];
        let ptr: *const i32 = arr.as_ptr();
        
        // These operations are safe (no dereference)
        let is_null = ptr.is_null();
        let offset_ptr = unsafe { ptr.add(2) }; // add() is safe, dereferencing isn't
        let _alignment = ptr.align_offset(std::mem::align_of::<i32>());
        
        println!("Is null: {}, offset ptr exists: {}", is_null, !offset_ptr.is_null());
    }
    
    /// DO: Use raw pointers for implementing custom data structures
    pub struct LinkedList<T> {
        head: *mut Node<T>,
        len: usize,
    }
    
    struct Node<T> {
        data: T,
        next: *mut Node<T>,
    }
    
    impl<T> LinkedList<T> {
        pub fn new() -> Self {
            Self {
                head: ptr::null_mut(),
                len: 0,
            }
        }
        
        pub fn is_empty(&self) -> bool {
            self.head.is_null()
        }
    }
    
    /// DO: Document unsafe invariants clearly
    /// 
    /// # Safety
    /// - `ptr` must be valid and properly aligned
    /// - `ptr` must point to initialized memory
    /// - The memory must not be mutated by anything else during this call
    pub unsafe fn read_with_documentation(ptr: *const i32) -> i32 {
        ptr::read(ptr)
    }
}

/// Demonstrates IMPROPER use of raw pointers
mod raw_pointer_donts {
    use std::ptr;
    
    /// DON'T: Dereference a null pointer
    pub fn null_dereference() {
        let null_ptr: *const i32 = ptr::null();
        
        // This would be undefined behavior!
        // unsafe { let _ = *null_ptr; } // NEVER DO THIS
        
        // Always check first
        if !null_ptr.is_null() {
            unsafe { let _ = *null_ptr; }
        }
    }
    
    /// DON'T: Create aliased mutable references from raw pointers
    pub fn aliasing_violation() {
        let mut data = 42;
        let ptr1 = &mut data as *mut i32;
        let ptr2 = &mut data as *mut i32;
        
        // Creating two mutable references to the same data is UB!
        // unsafe {
        //     let ref1 = &mut *ptr1;
        //     let ref2 = &mut *ptr2; // UB: aliased mutable references
        // }
        
        // Fix: Only create one reference at a time
        unsafe {
            let ref1 = &mut *ptr1;
            *ref1 = 100;
        }
        // Now safe to create another
        unsafe {
            let ref2 = &mut *ptr2;
            println!("Value: {}", ref2);
        }
    }
    
    /// DON'T: Use dangling pointers
    pub fn dangling_pointer() {
        let dangling: *const i32;
        {
            let local = 42;
            dangling = &local as *const i32;
        } // local is dropped here
        
        // Using 'dangling' here would be undefined behavior!
        // unsafe { println!("{}", *dangling); } // NEVER DO THIS
    }
    
    /// DON'T: Forget about alignment requirements
    pub fn alignment_issues() {
        let data = [0u8; 8];
        let ptr = data.as_ptr();
        
        // Creating a misaligned pointer is technically allowed...
        let misaligned = unsafe { ptr.add(1) as *const u64 };
        
        // ...but dereferencing it is UB!
        // unsafe { let _ = *misaligned; } // UB: misaligned access
        
        // Fix: Check alignment first
        let offset = unsafe { ptr.add(1) }.align_offset(std::mem::align_of::<u64>());
        if offset != 0 {
            println!("Pointer is misaligned, need to offset by {} bytes", offset);
        }
    }
    
    /// DON'T: Use raw pointers when safe alternatives exist
    pub fn unnecessary_raw_pointers() {
        let data = vec![1, 2, 3, 4, 5];
        
        // DON'T: Use raw pointers for simple iteration
        // unsafe {
        //     let ptr = data.as_ptr();
        //     for i in 0..data.len() {
        //         println!("{}", *ptr.add(i));
        //     }
        // }
        
        // DO: Use safe iteration
        for item in &data {
            println!("{}", item);
        }
    }
}

// ============================================================================
// SECTION 3: SMART POINTERS
// ============================================================================

/// Demonstrates PROPER use of Box<T>
mod box_dos {
    /// DO: Use Box for heap allocation when needed
    pub fn heap_allocation() {
        // Large data on heap instead of stack
        let large_data = Box::new([0u64; 10000]);
        println!("Boxed array size: {} bytes", large_data.len() * 8);
    }
    
    /// DO: Use Box for recursive types
    pub enum Tree {
        Leaf(i32),
        Node {
            value: i32,
            left: Box<Tree>,
            right: Box<Tree>,
        },
    }
    
    pub fn recursive_type_example() {
        let tree = Tree::Node {
            value: 10,
            left: Box::new(Tree::Leaf(5)),
            right: Box::new(Tree::Node {
                value: 15,
                left: Box::new(Tree::Leaf(12)),
                right: Box::new(Tree::Leaf(18)),
            }),
        };
        println!("Created recursive tree");
        drop(tree); // Clean demonstration
    }
    
    /// DO: Use Box for dynamic dispatch with trait objects
    pub trait Drawable {
        fn draw(&self);
    }
    
    struct Circle { radius: f64 }
    struct Square { side: f64 }
    
    impl Drawable for Circle {
        fn draw(&self) { println!("Drawing circle with radius {}", self.radius); }
    }
    
    impl Drawable for Square {
        fn draw(&self) { println!("Drawing square with side {}", self.side); }
    }
    
    pub fn dynamic_dispatch() {
        let shapes: Vec<Box<dyn Drawable>> = vec![
            Box::new(Circle { radius: 5.0 }),
            Box::new(Square { side: 10.0 }),
        ];
        
        for shape in shapes {
            shape.draw();
        }
    }
    
    /// DO: Use Box::pin for self-referential futures/structs
    pub fn pinning_example() {
        use std::pin::Pin;
        
        let value = Box::pin(42);
        println!("Pinned value: {}", value);
    }
}

mod box_donts {
    /// DON'T: Use Box unnecessarily for small, stack-friendly types
    pub fn unnecessary_boxing() {
        // DON'T: Box small values that fit on stack
        // let x = Box::new(42); // Unnecessary overhead
        // let y = Box::new(true); // Unnecessary overhead
        
        // DO: Just use stack
        let x = 42;
        let y = true;
        println!("Stack values: {}, {}", x, y);
    }
    
    /// DON'T: Forget that Box can be dereferenced
    pub fn unnecessary_deref() {
        let boxed = Box::new(String::from("Hello"));
        
        // DON'T: Manual dereference when not needed
        // let len = (*boxed).len();
        
        // DO: Use automatic deref coercion
        let len = boxed.len();
        println!("Length: {}", len);
    }
}

/// Demonstrates PROPER use of Rc<T> (Reference Counted)
mod rc_dos {
    use std::rc::{Rc, Weak};
    
    /// DO: Use Rc for shared ownership in single-threaded contexts
    pub fn shared_ownership() {
        let shared = Rc::new(String::from("Shared data"));
        
        // Clone creates another reference, not a copy of data
        let clone1 = Rc::clone(&shared);
        let clone2 = Rc::clone(&shared);
        
        println!("Reference count: {}", Rc::strong_count(&shared)); // 3
        
        // All point to same data
        println!("All same: {}", std::ptr::eq(&*shared, &*clone1));
        
        drop(clone2);
        println!("After drop: {}", Rc::strong_count(&shared)); // 2
    }
    
    /// DO: Use Weak to prevent reference cycles
    pub struct Node {
        value: i32,
        children: Vec<Rc<Node>>,
        parent: Weak<Node>, // Weak to avoid cycle!
    }
    
    impl Node {
        fn new(value: i32) -> Rc<Self> {
            Rc::new(Node {
                value,
                children: Vec::new(),
                parent: Weak::new(),
            })
        }
        
        fn add_child(parent: &Rc<Self>, child_value: i32) -> Rc<Self> {
            let child = Rc::new(Node {
                value: child_value,
                children: Vec::new(),
                parent: Rc::downgrade(parent),
            });
            parent.children.push(Rc::clone(&child));
            child
        }
    }
    
    pub fn tree_with_weak_parents() {
        let root = Node::new(1);
        let child1 = Node::add_child(&root, 2);
        let child2 = Node::add_child(&root, 3);
        
        println!("Root children: {}", root.children.len());
        println!("Child1 parent: {:?}", child1.parent.upgrade().map(|p| p.value));
        
        // When root is dropped, children can still be cleaned up
        // because parent references are weak
    }
    
    /// DO: Check Weak::upgrade() result
    pub fn safe_weak_usage(weak: Weak<String>) -> Option<String> {
        weak.upgrade().map(|rc| rc.to_string())
    }
}

mod rc_donts {
    use std::rc::Rc;
    
    /// DON'T: Use Rc across threads
    /// 
    /// This would NOT compile - Rc is not Send/Sync
    pub fn rc_not_thread_safe() {
        let data = Rc::new(String::from("Not thread safe"));
        
        // std::thread::spawn(move || {
        //     println!("{}", data); // ERROR: Rc cannot be sent between threads
        // });
        
        // Fix: Use Arc instead
        drop(data);
        println!("Use Arc for thread-safe sharing");
    }
    
    /// DON'T: Create reference cycles with Rc
    pub fn reference_cycle_warning() {
        // This structure would cause a memory leak:
        // struct BadNode {
        //     next: Option<Rc<BadNode>>, // Strong reference creates cycle
        //     prev: Option<Rc<BadNode>>, // Strong reference creates cycle
        // }
        
        // Fix: Use Weak for one direction
        println!("Always use Weak for back-references to avoid cycles");
    }
}

/// Demonstrates PROPER use of Arc<T> (Atomically Reference Counted)
mod arc_dos {
    use std::sync::{Arc, Mutex};
    use std::thread;
    
    /// DO: Use Arc for shared ownership across threads
    pub fn thread_safe_sharing() {
        let data = Arc::new(vec![1, 2, 3, 4, 5]);
        
        let mut handles = vec![];
        
        for i in 0..3 {
            let data_clone = Arc::clone(&data);
            handles.push(thread::spawn(move || {
                println!("Thread {}: {:?}", i, data_clone);
            }));
        }
        
        for handle in handles {
            handle.join().unwrap();
        }
    }
    
    /// DO: Combine Arc with Mutex for mutable shared state
    pub fn arc_with_mutex() {
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
        
        println!("Final counter: {}", *counter.lock().unwrap());
    }
    
    /// DO: Use Arc::new_cyclic for self-referential structures
    pub fn arc_cyclic() {
        use std::sync::Weak;
        
        struct SelfRef {
            self_ref: Weak<Self>,
            data: String,
        }
        
        let self_ref = Arc::new_cyclic(|weak| {
            SelfRef {
                self_ref: weak.clone(),
                data: "I know myself".to_string(),
            }
        });
        
        println!("Self-referential Arc created");
        if let Some(strong) = self_ref.self_ref.upgrade() {
            println!("Data: {}", strong.data);
        }
    }
}

mod arc_donts {
    use std::sync::Arc;
    
    /// DON'T: Use Arc unnecessarily in single-threaded code
    pub fn unnecessary_arc() {
        // DON'T: Use Arc when Rc would suffice (single thread)
        // let data = Arc::new(String::from("single threaded"));
        
        // DO: Use Rc for single-threaded scenarios
        // (Shown conceptually - actual Rc usage in rc_dos module)
        println!("Use Rc for single-threaded, Arc for multi-threaded");
    }
    
    /// DON'T: Hold locks across await points in async code
    pub fn lock_across_await_warning() {
        // In async code:
        // async fn bad() {
        //     let data = Arc::new(Mutex::new(0));
        //     let guard = data.lock().unwrap();
        //     some_async_fn().await; // BAD: Holding lock across await!
        // }
        
        // Fix: Drop lock before awaiting
        // async fn good() {
        //     let data = Arc::new(Mutex::new(0));
        //     {
        //         let mut guard = data.lock().unwrap();
        //         *guard += 1;
        //     } // Lock dropped here
        //     some_async_fn().await; // Safe now
        // }
        
        println!("Never hold Mutex locks across await points");
    }
}

/// Demonstrates PROPER use of RefCell<T>
mod refcell_dos {
    use std::cell::RefCell;
    
    /// DO: Use RefCell for interior mutability when needed
    pub fn interior_mutability() {
        let data = RefCell::new(vec![1, 2, 3]);
        
        // We can modify through immutable reference!
        data.borrow_mut().push(4);
        
        // Multiple immutable borrows at runtime
        let r1 = data.borrow();
        let r2 = data.borrow();
        
        println!("Borrowed twice: {:?}, {:?}", *r1, *r2);
    }
    
    /// DO: Use RefCell in structs that need mutation through shared references
    pub struct Graph {
        nodes: RefCell<Vec<String>>,
    }
    
    impl Graph {
        fn new() -> Self {
            Graph {
                nodes: RefCell::new(Vec::new()),
            }
        }
        
        // Can take &self and still mutate
        fn add_node(&self, name: &str) {
            self.nodes.borrow_mut().push(name.to_string());
        }
        
        fn node_count(&self) -> usize {
            self.nodes.borrow().len()
        }
    }
    
    pub fn graph_example() {
        let graph = Graph::new();
        graph.add_node("A");
        graph.add_node("B");
        println!("Node count: {}", graph.node_count());
    }
    
    /// DO: Handle borrow errors gracefully
    pub fn graceful_error_handling(cell: &RefCell<Vec<i32>>) -> Option<usize> {
        match cell.try_borrow_mut() {
            Ok(mut guard) => {
                guard.push(1);
                Some(guard.len())
            }
            Err(_) => {
                println!("Cell is already borrowed");
                None
            }
        }
    }
}

mod refcell_donts {
    use std::cell::RefCell;
    
    /// DON'T: Create aliased mutable references at runtime
    pub fn runtime_panic() {
        let cell = RefCell::new(42);
        
        let borrow1 = cell.borrow_mut();
        // let borrow2 = cell.borrow_mut(); // This PANICS at runtime!
        
        println!("First borrow: {}", borrow1);
        drop(borrow1); // Must drop before next borrow
        
        let borrow2 = cell.borrow_mut(); // Now safe
        println!("Second borrow: {}", borrow2);
    }
    
    /// DON'T: Use RefCell across threads
    /// 
    /// RefCell is not Sync - this wouldn't compile
    pub fn refcell_not_thread_safe() {
        // std::thread::spawn(|| {
        //     let cell = RefCell::new(42);
        //     // RefCell doesn't implement Sync
        // });
        
        println!("Use Mutex instead of RefCell for thread-safety");
    }
    
    /// DON'T: Forget that RefCell has runtime overhead
    pub fn overhead_awareness() {
        // RefCell adds runtime checks - only use when necessary
        // For purely immutable data, just use regular references
        
        // DON'T: Use RefCell for everything
        // let x = RefCell::new(42); // Overkill for simple cases
        
        // DO: Use plain values when possible
        let x = 42;
        println!("Plain value: {}", x);
    }
}

/// Demonstrates PROPER use of Cow<T> (Clone on Write)
mod cow_dos {
    use std::borrow::Cow;
    
    /// DO: Use Cow to avoid unnecessary allocations
    pub fn avoid_allocation() {
        fn process(input: &str) -> Cow<str> {
            if input.contains(' ') {
                // Need to allocate for modification
                Cow::Owned(input.replace(' ', "_"))
            } else {
                // No allocation - just borrow
                Cow::Borrowed(input)
            }
        }
        
        let no_change = process("hello");
        let with_change = process("hello world");
        
        println!("No change (borrowed): {}", no_change);
        println!("With change (owned): {}", with_change);
    }
    
    /// DO: Use Cow for function parameters that might need modification
    pub fn flexible_parameter(data: Cow<str>) {
        // Function works with either borrowed or owned data
        println!("Processing: {}", data);
    }
    
    pub fn cow_parameter_example() {
        let owned = String::from("owned string");
        let borrowed = "borrowed string";
        
        flexible_parameter(Cow::Owned(owned));
        flexible_parameter(Cow::Borrowed(borrowed));
        
        // Or with Into<Cow>:
        flexible_parameter(String::from("from owned").into());
        flexible_parameter("from borrowed".into());
    }
}

mod cow_donts {
    use std::borrow::Cow;
    
    /// DON'T: Use Cow when you always need ownership
    pub fn always_owned_case() {
        // If you always need to modify, just take ownership
        // DON'T:
        // fn bad(data: Cow<str>) -> String {
        //     data.into_owned().to_uppercase() // Always converts anyway
        // }
        
        // DO:
        fn good(data: String) -> String {
            data.to_uppercase()
        }
        
        let _ = good("test".to_string());
    }
    
    /// DON'T: Forget that to_mut() may allocate
    pub fn unexpected_allocation() {
        let borrowed: Cow<str> = Cow::Borrowed("hello");
        
        // This ALLOCATES because we're modifying borrowed data
        let mutated = borrowed.to_mut();
        mutated.make_ascii_uppercase();
        
        println!("Allocated when mutated: {}", mutated);
    }
}

// ============================================================================
// SECTION 4: ADVANCED PATTERNS AND BEST PRACTICES
// ============================================================================

mod advanced_patterns {
    use std::cell::Cell;
    use std::rc::Rc;
    use std::sync::atomic::{AtomicUsize, Ordering};
    
    /// Pattern: Use Cell for Copy types when you need interior mutability
    pub fn cell_for_copy_types() {
        let counter = Cell::new(0);
        
        counter.set(counter.get() + 1);
        counter.set(counter.get() + 1);
        
        println!("Cell counter: {}", counter.get());
    }
    
    /// Pattern: Use OnceCell for lazy initialization
    pub fn once_cell_pattern() {
        use std::cell::OnceCell;
        
        let lazy = OnceCell::new();
        
        assert!(lazy.get().is_none());
        
        let value = lazy.get_or_init(|| {
            println!("Computing expensive value...");
            42
        });
        
        println!("Value: {}", value);
        
        // Second call doesn't recompute
        let _ = lazy.get_or_init(|| {
            println!("This won't print");
            100
        });
    }
    
    /// Pattern: Use Atomic types for lock-free counters
    pub fn atomic_counter() {
        let counter = Arc::new(AtomicUsize::new(0));
        let counter_clone = Arc::clone(&counter);
        
        std::thread::spawn(move || {
            counter_clone.fetch_add(1, Ordering::SeqCst);
        }).join().unwrap();
        
        println!("Atomic counter: {}", counter.load(Ordering::SeqCst));
    }
    
    /// Pattern: Builder with owned/borrowed flexibility
    pub struct Config<'a> {
        name: Cow<'a, str>,
        value: Option<i32>,
    }
    
    impl<'a> Config<'a> {
        pub fn new(name: impl Into<Cow<'a, str>>) -> Self {
            Config {
                name: name.into(),
                value: None,
            }
        }
        
        pub fn with_value(mut self, value: i32) -> Self {
            self.value = Some(value);
            self
        }
    }
    
    pub fn builder_example() {
        let config1 = Config::new("static_name").with_value(42);
        let dynamic_name = String::from("dynamic_name");
        let config2 = Config::new(&dynamic_name).with_value(100);
        
        println!("Config1 name: {}", config1.name);
        println!("Config2 name: {}", config2.name);
    }
}

// ============================================================================
// SECTION 5: COMMON MISTAKES SUMMARY
// ============================================================================

mod common_mistakes {
    /// Mistake 1: Forgetting that moves invalidate old bindings
    pub fn move_invalidation() {
        let s1 = String::from("hello");
        let s2 = s1; // s1 is MOVED, no longer valid
        
        // println!("{}", s1); // ERROR: value borrowed after move
        
        println!("Only s2 valid: {}", s2);
        
        // Fix: Clone if you need both
        let s3 = String::from("world");
        let s4 = s3.clone();
        println!("Both valid: {} {}", s3, s4);
    }
    
    /// Mistake 2: Trying to borrow after partial move
    pub fn partial_move_issue() {
        let tuple = (String::from("hello"), 42);
        
        let _ = tuple.0; // Partial move of tuple.0
        
        // println!("{}", tuple.0); // ERROR: partially moved
        println!("tuple.1 still valid: {}", tuple.1); // tuple.1 is fine
    }
    
    /// Mistake 3: Not understanding lifetime elision rules
    pub fn lifetime_elision() {
        // These two are equivalent due to elision rules:
        fn implicit(s: &str) -> &str { s }
        fn explicit<'a>(s: &'a str) -> &'a str { s }
        
        println!("Both work: {} {}", implicit("a"), explicit("b"));
        
        // But this needs explicit lifetime:
        // fn bad(s1: &str, s2: &str) -> &str { s1 } // ERROR
        fn good<'a>(s1: &'a str, _s2: &str) -> &'a str { s1 }
        
        println!("Explicit needed: {}", good("first", "second"));
    }
    
    /// Mistake 4: Fighting the borrow checker instead of redesigning
    pub fn borrow_checker_fighting() {
        // BAD APPROACH: Trying to make complex borrowing work
        // Often leads to ugly code with lots of scopes
        
        // GOOD APPROACH: Restructure data
        // Use indices instead of pointers
        // Split structs if needed
        // Use collections that support interior mutability
        
        struct Game {
            players: Vec<Player>,
            current_player: usize, // Index, not reference!
        }
        
        struct Player {
            name: String,
            score: i32,
        }
        
        let mut game = Game {
            players: vec![
                Player { name: "Alice".into(), score: 0 },
                Player { name: "Bob".into(), score: 0 },
            ],
            current_player: 0,
        };
        
        // Clean access using index
        game.players[game.current_player].score += 10;
        println!("{} scored: {}", 
            game.players[game.current_player].name,
            game.players[game.current_player].score);
    }
}

// ============================================================================
// MAIN FUNCTION - DEMONSTRATE ALL CONCEPTS
// ============================================================================

fn main() {
    println!("╔══════════════════════════════════════════════════════════════╗");
    println!("║     RUST POINTERS: COMPREHENSIVE DO'S AND DON'TS GUIDE     ║");
    println!("╚══════════════════════════════════════════════════════════════╝\n");

    // Section 1: References
    println!("━━━ SECTION 1: REFERENCES (BORROWED POINTERS) ━━━\n");
    
    println!("✅ DO: Multiple immutable references");
    reference_dos::multiple_readers();
    
    println!("\n✅ DO: Single mutable reference at a time");
    reference_dos::single_writer();
    
    println!("\n✅ DO: Proper lifetime annotations");
    let trimmed = reference_dos::proper_lifetimes("  hello  ");
    println!("Trimmed: '{}'", trimmed);
    
    println!("\n✅ DO: Efficient parameter passing");
    let data = vec![1u8, 2, 3, 4, 5];
    println!("Length: {}", reference_dos::efficient_parameter_passing(&data));
    
    println!("\n✅ DO: Reborrowing");
    reference_dos::reborrowing_example();
    
    println!("\n❌ DON'T: Simultaneous mutable and immutable borrows (compile error if attempted)");
    reference_donts::simultaneous_borrows();
    
    println!("\n❌ DON'T: Return dangling references (compile error if attempted)");
    let static_str = reference_donts::dangling_reference();
    println!("Safe static reference: {}", static_str);

    // Section 2: Raw Pointers
    println!("\n━━━ SECTION 2: RAW POINTERS ━━━\n");
    
    println!("✅ DO: Safe FFI-style usage");
    raw_pointer_dos::ffi_safe_usage();
    
    println!("\n✅ DO: NonNull for guaranteed non-null");
    raw_pointer_dos::nonnull_usage();
    
    println!("\n✅ DO: Null checking");
    let result = raw_pointer_dos::safe_null_check(std::ptr::null());
    println!("Null check result: {:?}", result);
    
    println!("\n✅ DO: Safe pointer operations (no dereference)");
    raw_pointer_dos::safe_pointer_operations();
    
    println!("\n✅ DO: Raw pointers in custom data structures");
    let list = raw_pointer_dos::LinkedList::<i32>::new();
    println!("Empty list: {}", list.is_empty());
    
    println!("\n❌ DON'T: Null dereference (would be UB)");
    raw_pointer_donts::null_dereference();
    
    println!("\n❌ DON'T: Aliased mutable references from raw pointers (would be UB)");
    raw_pointer_donts::aliasing_violation();
    
    println!("\n❌ DON'T: Dangling pointers (would be UB)");
    raw_pointer_donts::dangling_pointer();
    
    println!("\n❌ DON'T: Misaligned pointer access (would be UB)");
    raw_pointer_donts::alignment_issues();
    
    println!("\n❌ DON'T: Use raw pointers when safe alternatives exist");
    raw_pointer_donts::unnecessary_raw_pointers();

    // Section 3: Smart Pointers
    println!("\n━━━ SECTION 3: SMART POINTERS ━━━\n");
    
    println!("--- Box<T> ---");
    println!("✅ DO: Heap allocation for large data");
    box_dos::heap_allocation();
    
    println!("\n✅ DO: Box for recursive types");
    box_dos::recursive_type_example();
    
    println!("\n✅ DO: Box for dynamic dispatch");
    box_dos::dynamic_dispatch();
    
    println!("\n❌ DON'T: Unnecessary boxing of small values");
    box_donts::unnecessary_boxing();
    
    println!("\n--- Rc<T> ---");
    println!("✅ DO: Rc for shared ownership (single-threaded)");
    rc_dos::shared_ownership();
    
    println!("\n✅ DO: Weak to prevent reference cycles");
    rc_dos::tree_with_weak_parents();
    
    println!("\n❌ DON'T: Use Rc across threads (won't compile)");
    rc_donts::rc_not_thread_safe();
    
    println!("\n❌ DON'T: Create reference cycles with Rc");
    rc_donts::reference_cycle_warning();
    
    println!("\n--- Arc<T> ---");
    println!("✅ DO: Arc for thread-safe sharing");
    arc_dos::thread_safe_sharing();
    
    println!("\n✅ DO: Arc with Mutex for mutable shared state");
    arc_dos::arc_with_mutex();
    
    println!("\n✅ DO: Arc::new_cyclic for self-referential structures");
    arc_dos::arc_cyclic();
    
    println!("\n❌ DON'T: Use Arc unnecessarily in single-threaded code");
    arc_donts::unnecessary_arc();
    
    println!("\n❌ DON'T: Hold locks across await points");
    arc_donts::lock_across_await_warning();
    
    println!("\n--- RefCell<T> ---");
    println!("✅ DO: RefCell for interior mutability");
    refcell_dos::interior_mutability();
    
    println!("\n✅ DO: RefCell in structs");
    refcell_dos::graph_example();
    
    println!("\n✅ DO: Handle borrow errors gracefully");
    let cell = std::cell::RefCell::new(vec![1, 2, 3]);
    println!("Graceful borrow result: {:?}", refcell_dos::graceful_error_handling(&cell));
    
    println!("\n❌ DON'T: Create aliased mutable references at runtime (panics)");
    refcell_donts::runtime_panic();
    
    println!("\n❌ DON'T: Use RefCell across threads (won't compile)");
    refcell_donts::refcell_not_thread_safe();
    
    println!("\n❌ DON'T: Use RefCell unnecessarily (has runtime overhead)");
    refcell_donts::overhead_awareness();
    
    println!("\n--- Cow<T> ---");
    println!("✅ DO: Use Cow to avoid unnecessary allocations");
    cow_dos::avoid_allocation();
    
    println!("\n✅ DO: Cow for flexible function parameters");
    cow_dos::cow_parameter_example();
    
    println!("\n❌ DON'T: Use Cow when you always need ownership");
    cow_donts::always_owned_case();
    
    println!("\n❌ DON'T: Forget that to_mut() may allocate");
    cow_donts::unexpected_allocation();

    // Section 4: Advanced Patterns
    println!("\n━━━ SECTION 4: ADVANCED PATTERNS ━━━\n");
    
    println!("✅ Cell for Copy types");
    advanced_patterns::cell_for_copy_types();
    
    println!("\n✅ OnceCell for lazy initialization");
    advanced_patterns::once_cell_pattern();
    
    println!("\n✅ Atomic types for lock-free operations");
    advanced_patterns::atomic_counter();
    
    println!("\n✅ Builder pattern with Cow flexibility");
    advanced_patterns::builder_example();

    // Section 5: Common Mistakes
    println!("\n━━━ SECTION 5: COMMON MISTAKES ━━━\n");
    
    println!("⚠️  Mistake: Move invalidation");
    common_mistakes::move_invalidation();
    
    println!("\n⚠️  Mistake: Partial move issues");
    common_mistakes::partial_move_issue();
    
    println!("\n⚠️  Mistake: Lifetime elision understanding");
    common_mistakes::lifetime_elision();
    
    println!("\n⚠️  Mistake: Fighting the borrow checker");
    common_mistakes::borrow_checker_fighting();

    // Summary
    println!("\n━━━ QUICK REFERENCE SUMMARY ━━━\n");
    print_summary();
}

fn print_summary() {
    println!("┌─────────────────────────────────────────────────────────────────┐");
    println!("│                     POINTER CHEAT SHEET                         │");
    println!("├─────────────────────────────────────────────────────────────────┤");
    println!("│ &T              │ Immutable borrow, multiple allowed            │");
    println!("│ &mut T          │ Mutable borrow, only ONE at a time            │");
    println!("│ *const T        │ Raw read-only pointer, unsafe to deref        │");
    println!("│ *mut T          │ Raw mutable pointer, unsafe to deref          │");
    println!("│ Box<T>          │ Heap allocation, single owner                 │");
    println!("│ Rc<T>           │ Reference counting, NOT thread-safe           │");
    println!("│ Arc<T>          │ Atomic ref counting, thread-safe              │");
    println!("│ Weak<T>         │ Weak reference, doesn't prevent drop          │");
    println!("│ RefCell<T>      │ Runtime borrow checking, NOT thread-safe      │");
    println!("│ Cell<T>         │ Interior mutability for Copy types            │");
    println!("│ Mutex<T>        │ Mutual exclusion, thread-safe                 │");
    println!("│ Cow<T>          │ Clone-on-write, borrow or own                │");
    println!("├─────────────────────────────────────────────────────────────────┤");
    println!("│ USE:                                                            │");
    println!("│   • &T/&mut T for most cases (zero cost)                        │");
    println!("│   • Box for large data, recursive types, trait objects          │");
    println!("│   • Rc/Arc for shared ownership                                 │");
    println!("│   • RefCell/Cell when you NEED interior mutability              │");
    println!("│   • Raw pointers ONLY for FFI or low-level data structures     │");
    println!("│   • Cow to avoid allocations when possible                      │");
    println!("├─────────────────────────────────────────────────────────────────┤");
    println!("│ AVOID:                                                          │");
    println!("│   • Raw pointers unless absolutely necessary                    │");
    println!("│   • Reference cycles (use Weak)                                 │");
    println!("│   • Rc/Arc across wrong thread boundaries                       │");
    println!("│   • Holding Mutex locks across await points                     │");
    println!("│   • Unnecessary boxing/allocation                               │");
    println!("│   • Fighting the borrow checker - redesign instead              │");
    println!("└─────────────────────────────────────────────────────────────────┘");
}