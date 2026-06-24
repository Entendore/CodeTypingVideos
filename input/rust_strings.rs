// ============================================================================
// COMPLETE RUST STRINGS GUIDE
// ============================================================================
// Rust has multiple string types for different purposes:
// 1. str       - String slice (fixed-size, view into string data)
// 2. String    - Heap-allocated, growable, owned string
// 3. OsStr/OsString - Platform-specific strings (for OS interactions)
// 4. CStr/CString   - C-compatible strings (null-terminated)
// 5. Path/PathBuf   - File system path strings
// ============================================================================

use std::ffi::{CStr, CString, OsStr, OsString};
use std::path::{Path, PathBuf};
use std::str::FromStr;

fn main() {
    println!("{}" , "=".repeat(70));
    println!("         COMPLETE RUST STRINGS GUIDE");
    println!("{}" , "=".repeat(70));
    
    // ========================================================================
    // 1. &str - STRING SLICE (THE MOST BASIC STRING TYPE)
    // ========================================================================
    section_header("1. &str - STRING SLICE");
    
    /*
    WHAT IS &str?
    - It's a "borrowed" reference to a string
    - Always stored somewhere else (static memory, heap, stack)
    - Has a fixed length (cannot grow or shrink)
    - Consists of: (pointer to data, length)
    - Is NOT heap-allocated by itself
    - UTF-8 encoded by default
    */
    
    // Different ways to create &str
    
    // Method 1: String literal (stored in binary's read-only memory)
    let hello: &str = "Hello, World!";
    println!("String literal: {}", hello);
    println!("  - Type: &str (immutable reference to str)");
    println!("  - Stored in: Binary's static memory (read-only)");
    
    // Method 2: Explicit type annotation
    let greeting: &'static str = "Greetings";
    println!("\nStatic str: {}", greeting);
    println!("  - 'static lifetime: lives for entire program duration");
    
    // Method 3: Slicing a String or &str
    let text = "Hello, Rust!";
    let slice: &str = &text[0..5]; // "Hello"
    println!("\nSliced: '{}' (from index 0 to 5)", slice);
    println!("  - Created by slicing: &text[0..5]");
    
    // Method 4: From String dereferencing
    let owned_string = String::from("Owned");
    let borrowed: &str = &owned_string; // Deref coercion
    println!("\nBorrowed from String: {}", borrowed);
    println!("  - String automatically coerces to &str");
    
    // Important: str without & is unsized (cannot be used directly)
    // let s: str = "hello"; // ERROR! str is unsized
    // You must always use &str or Box<str>, etc.
    
    println!("\nKEY POINTS ABOUT &str:");
    println!("  • Cheap to copy (just copies pointer + length)");
    println!("  • Immutable by default");
    println!("  • Cannot be modified in place");
    println!("  • Ideal for function parameters (borrowing)");
    println!("  • Used for string literals");
    
    // ========================================================================
    // 2. String - HEAP-ALLOCATED GROWABLE STRING
    // ========================================================================
    section_header("2. String - HEAP-ALLOCATED STRING");
    
    /*
    WHAT IS String?
    - Heap-allocated, growable string buffer
    - Owned type (you control its lifetime)
    - UTF-8 encoded
    - Consists of: (pointer to heap, length, capacity)
    - Can be modified (push, pop, insert, etc.)
    - When dropped, heap memory is freed
    */
    
    // Method 1: String::new() - creates empty String
    let mut empty_string = String::new();
    println!("Empty String: '{}' (length: {})", empty_string, empty_string.len());
    println!("  - Created with String::new()");
    println!("  - Capacity: {}", empty_string.capacity());
    
    // Method 2: String::from() - from &str
    let from_str = String::from("From &str");
    println!("\nString::from(): {}", from_str);
    
    // Method 3: .to_string() - converts &str to String
    let to_string = "Convert me".to_string();
    println!("to_string(): {}", to_string);
    
    // Method 4: String::with_capacity() - pre-allocate
    let mut with_capacity = String::with_capacity(100);
    println!("\nWith capacity: '{}' (capacity: {})", with_capacity, with_capacity.capacity());
    println!("  - Pre-allocates memory to avoid reallocations");
    
    // Method 5: From iterator of chars
    let from_chars: String = ['H', 'e', 'l', 'l', 'o'].iter().collect();
    println!("\nFrom chars: {}", from_chars);
    
    // Method 6: From iterator of bytes (must be valid UTF-8)
    let bytes: Vec<u8> = vec![72, 105]; // "Hi"
    let from_bytes = String::from_utf8(bytes).unwrap();
    println!("From bytes: {}", from_bytes);
    
    // Method 7: String::from_utf8_lossy() - replaces invalid bytes
    let invalid_bytes: Vec<u8> = vec![255, 72, 105]; // 255 is invalid UTF-8
    let lossy = String::from_utf8_lossy(&invalid_bytes);
    println!("From bytes (lossy): {}", lossy); // Shows Hi
    
    println!("\nKEY POINTS ABOUT String:");
    println!("  • Owned - freed when it goes out of scope");
    println!("  • Mutable - can be modified");
    println!("  • Growable - can increase in size");
    println!("  • Heap-allocated - has overhead");
    println!("  • Can be converted to &str for borrowing");
    
    // ========================================================================
    // 3. STRING MODIFICATION METHODS
    // ========================================================================
    section_header("3. STRING MODIFICATION METHODS");
    
    let mut s = String::from("Hello");
    
    // push_str() - append &str
    s.push_str(", World");
    println!("After push_str: {}", s);
    
    // push() - append single char
    s.push('!');
    println!("After push: {}", s);
    
    // insert() - insert char at position
    s.insert(5, ' ');
    println!("After insert: {}", s);
    
    // insert_str() - insert &str at position
    s.insert_str(6, "Beautiful ");
    println!("After insert_str: {}", s);
    
    // remove() - remove char at byte index (returns the char)
    let removed = s.remove(6); // Removes 'B'
    println!("After remove('{}'): {}", removed, s);
    
    // pop() - remove last char (returns Option<char>)
    let popped = s.pop(); // Removes '!'
    println!("After pop({:?}): {}", popped, s);
    
    // truncate() - shorten to byte index
    let mut trunc = String::from("Hello World");
    trunc.truncate(5);
    println!("\nAfter truncate(5): {}", trunc);
    
    // clear() - remove all content
    let mut clear_me = String::from("Delete me");
    clear_me.clear();
    println!("After clear: '{}' (len: {})", clear_me, clear_me.len());
    
    // replace() - replace all occurrences (returns new String)
    let original = "hello hello hello";
    let replaced = original.replace("hello", "hi");
    println!("\nReplace 'hello' with 'hi': {} -> {}", original, replaced);
    
    // replacen() - replace n occurrences
    let replaced_n = original.replacen("hello", "hi", 2);
    println!("Replace first 2: {}", replaced_n);
    
    // retain() - keep only chars matching predicate
    let mut keep_letters = String::from("He11o W0r1d!");
    keep_letters.retain(|c| c.is_alphabetic() || c.is_whitespace());
    println!("After retain (letters only): {}", keep_letters);
    
    // ========================================================================
    // 4. STRING CONCATENATION
    // ========================================================================
    section_header("4. STRING CONCATENATION");
    
    // Method 1: + operator (takes ownership of first String)
    let s1 = String::from("Hello");
    let s2 = String::from(" World");
    let s3 = s1 + &s2; // s1 is moved, s2 is borrowed
    println!("+ operator: {}", s3);
    // println!("{}", s1); // ERROR! s1 was moved
    
    // Method 2: format! macro (doesn't take ownership)
    let s1 = String::from("Hello");
    let s2 = String::from(" World");
    let s3 = format!("{}{}", s1, s2);
    println!("format! macro: {}", s3);
    println!("  - s1 still valid: {}", s1);
    println!("  - s2 still valid: {}", s2);
    
    // Method 3: concat! macro (compile-time)
    let concatenated = concat!("Hello", " ", "World", "!");
    println!("concat! macro: {}", concatenated);
    
    // Method 4: Multiple + operators
    let multi = String::from("A") + " + " + "B" + " + " + "C";
    println!("Multiple +: {}", multi);
    
    // ========================================================================
    // 5. STRING INDEXING AND SLICING
    // ========================================================================
    section_header("5. STRING INDEXING AND SLICING");
    
    let text = "Hello, 世界!"; // Mix of ASCII and Unicode
    
    println!("Original: '{}' (length: {} bytes)", text, text.len());
    println!("  - Note: len() returns BYTES, not characters!");
    println!("  - '世' is 3 bytes, '界' is 3 bytes");
    
    // Getting individual characters with .chars()
    println!("\nCharacters:");
    for (i, ch) in text.chars().enumerate() {
        println!("  [{}] '{}' ({} bytes)", i, ch, ch.len_utf8());
    }
    
    // Byte indexing (DANGEROUS - can panic!)
    println!("\nByte indexing:");
    println!("  text.as_bytes(): {:?}", text.as_bytes());
    println!("  &text[0..1] = '{}'", &text[0..1]); // 'H'
    println!("  &text[0..5] = '{}'", &text[0..5]); // "Hello"
    // &text[0..6] = ',' // "Hello,"
    // &text[7..10] = '世' // But this is tricky!
    
    // Safe slicing with .get()
    println!("\nSafe slicing with .get():");
    match text.get(0..5) {
        Some(slice) => println!("  text.get(0..5) = Some(\"{}\")", slice),
        None => println!("  text.get(0..5) = None"),
    }
    
    match text.get(5..6) { // Valid UTF-8 boundary
        Some(slice) => println!("  text.get(5..6) = Some(\"{}\")", slice),
        None => println!("  text.get(5..6) = None"),
    }
    
    // Invalid slice (middle of multi-byte char) - returns None
    match text.get(8..9) { // Middle of '世'
        Some(slice) => println!("  text.get(8..9) = Some(\"{}\")", slice),
        None => println!("  text.get(8..9) = None (invalid UTF-8 boundary)"),
    }
    
    // ========================================================================
    // 6. STRING ITERATION METHODS
    // ========================================================================
    section_header("6. STRING ITERATION METHODS");
    
    let text = "Hello\nWorld\r\nRust";
    
    // chars() - iterate over Unicode scalar values
    println!("chars():");
    for ch in text.chars() {
        if ch != '\n' && ch != '\r' {
            print!("'{}' ", ch);
        } else {
            print!("'\\n'/'\\r' ");
        }
    }
    println!();
    
    // bytes() - iterate over raw bytes
    println!("\nbytes() (first 10):");
    for (i, byte) in text.bytes().take(10).enumerate() {
        print!("[{}]{} ", i, byte);
    }
    println!();
    
    // char_indices() - iterate with byte indices
    println!("\nchar_indices():");
    for (i, ch) in text.char_indices().take(5) {
        println!("  byte[{}] = '{}'", i, ch);
    }
    
    // lines() - iterate over lines (without newline chars)
    println!("\nlines():");
    for line in text.lines() {
        println!("  '{}'", line);
    }
    
    // split() - split by pattern
    println!("\nsplit(' '):");
    let sentence = "one two three four";
    for part in sentence.split(' ') {
        print!("'{}' ", part);
    }
    println!();
    
    // split_whitespace() - split by any whitespace
    println!("\nsplit_whitespace():");
    let with_spaces = "  one   two\tthree\nfour  ";
    for part in with_spaces.split_whitespace() {
        print!("'{}' ", part);
    }
    println!();
    
    // split_inclusive() - include delimiter in results
    println!("\nsplit_inclusive(','):");
    for part in "a,b,c,d".split_inclusive(',') {
        print!("'{}' ", part);
    }
    println!();
    
    // windows() - sliding windows of chars
    println!("\nwindows(2) on 'abcdef':");
    for w in "abcdef".chars().collect::<String>().as_str().windows(2) {
        print!("'{}' ", w);
    }
    println!();
    
    // ========================================================================
    // 7. STRING SEARCH AND QUERY METHODS
    // ========================================================================
    section_header("7. STRING SEARCH AND QUERY METHODS");
    
    let text = "Hello, Rust Programming!";
    
    // contains() - check if pattern exists
    println!("contains(\"Rust\"): {}", text.contains("Rust"));
    println!("contains(\"Python\"): {}", text.contains("Python"));
    
    // starts_with() / ends_with()
    println!("starts_with(\"Hello\"): {}", text.starts_with("Hello"));
    println!("ends_with(\"!\"): {}", text.ends_with("!"));
    
    // find() - returns Option<usize> (byte index of first match)
    println!("\nfind(\"Rust\"): {:?}", text.find("Rust"));
    println!("find(\"Python\"): {:?}", text.find("Python"));
    
    // rfind() - find from right
    println!("rfind(\"!\"): {:?}", text.rfind("!"));
    
    // matches() - iterator over all matches
    println!("\nmatches([a-z]+):");
    for m in text.matches("[a-z]+") {
        print!("'{}' ", m);
    }
    println!();
    
    // match_indices() - matches with positions
    println!("\nmatch_indices(\"l\"):");
    for (start, end, m) in text.match_indices("l") {
        println!("  [{}..{}] = '{}'", start, end, m);
    }
    
    // ========================================================================
    // 8. STRING TRANSFORMATION METHODS
    // ========================================================================
    section_header("8. STRING TRANSFORMATION METHODS");
    
    let text = "Hello, World!";
    
    // to_uppercase() / to_lowercase()
    println!("Original: {}", text);
    println!("to_uppercase(): {}", text.to_uppercase());
    println!("to_lowercase(): {}", text.to_lowercase());
    
    // trim() / trim_start() / trim_end()
    let with_spaces = "   Hello, World!   ";
    println!("\nOriginal: '{}'", with_spaces);
    println!("trim(): '{}'", with_spaces.trim());
    println!("trim_start(): '{}'", with_spaces.trim_start());
    println!("trim_end(): '{}'", with_spaces.trim_end());
    
    // trim_matches() - remove specific chars
    let brackets = "***Hello***";
    println!("\ntrim_matches('*'): '{}'", brackets.trim_matches('*'));
    
    // strip_prefix() / strip_suffix() - returns Option
    let prefixed = "prefix:content";
    println!("\nstrip_prefix('prefix:'): {:?}", prefixed.strip_prefix("prefix:"));
    println!("strip_suffix('!'): {:?}", text.strip_suffix("!"));
    
    // repeat() - repeat string n times
    let repeated = "Ha".repeat(3);
    println!("\nrepeat(3): {}", repeated);
    
    // replace_range() - replace a range (in-place for String)
    let mut mutable = String::from("Hello, World!");
    mutable.replace_range(7..12, "Rust");
    println!("\nreplace_range(7..12, \"Rust\"): {}", mutable);
    
    // escape_unicode() / escape_default()
    let unicode = "é";
    println!("\nescape_unicode(): {}", unicode.escape_unicode());
    println!("escape_default(): {}", unicode.escape_default());
    
    // ========================================================================
    // 9. RAW STRINGS
    // ========================================================================
    section_header("9. RAW STRINGS");
    
    // Raw strings don't process escape sequences
    let raw = r"Hello\nWorld"; // \n is literal backslash-n
    println!("Raw string: {}", raw);
    
    // Raw string with quotes
    let with_quotes = r#"He said "Hello""#;
    println!("With quotes: {}", with_quotes);
    
    // Raw string with # in content - use more #'s
    let with_hash = r##"This has a # in it"##;
    println!("With hash: {}", with_hash);
    
    // Raw string spanning multiple lines
    let multi_line_raw = r"
Line 1
Line 2
    Line 3 (indented)
";
    println!("Multi-line raw:{}", multi_line_raw);
    
    // ========================================================================
    // 10. BYTE STRINGS
    // ========================================================================
    section_header("10. BYTE STRINGS");
    
    // Byte string literal: b"..."
    let byte_str: &[u8; 5] = b"Hello";
    println!("Byte string: {:?}", byte_str);
    
    // Byte string with escapes
    let byte_with_escape: &[u8; 2] = b"\x41\x42"; // "AB"
    println!("Byte with escape: {:?}", byte_with_escape);
    
    // Raw byte string
    let raw_bytes: &[u8] = br"Hello\nWorld";
    println!("Raw byte string: {:?}", raw_bytes);
    
    // Converting between &str and &[u8]
    let text: &str = "Hello";
    let bytes: &[u8] = text.as_bytes();
    println!("\n&str to &[u8]: {:?}", bytes);
    
    // &[u8] to &str (unsafe if not valid UTF-8!)
    let back_to_str: &str = std::str::from_utf8(bytes).unwrap();
    println!("[&u8] to &str: {}", back_to_str);
    
    // ========================================================================
    // 11. OsStr AND OsString (OS-SPECIFIC STRINGS)
    // ========================================================================
    section_header("11. OsStr AND OsString");
    
    /*
    WHAT ARE OsStr/OsString?
    - Platform-specific string types
    - On Unix: can be any sequence of bytes (not necessarily UTF-8)
    - On Windows: can be any sequence of 16-bit values
    - Used for: file names, environment variables, command-line args
    - OsStr = borrowed slice, OsString = owned
    */
    
    // Create OsString from &str
    let os_string = OsString::from("Hello, OS!");
    println!("OsString: {:?}", os_string);
    
    // Get OsStr from OsString
    let os_str: &OsStr = &os_string;
    println!("OsStr: {:?}", os_str);
    
    // Convert between String and OsString
    let string = String::from("Test");
    let os_from_string = OsString::from(&string);
    println!("\nString -> OsString: {:?}", os_from_string);
    
    // OsString -> String (can fail if not valid UTF-8)
    match os_from_string.into_string() {
        Ok(s) => println!("OsString -> String: {}", s),
        Err(e) => println!("OsString -> String failed: {:?}", e),
    }
    
    // OsString -> String (lossy - replaces invalid bytes)
    let os = OsString::from("Valid");
    let lossy_string = os.to_string_lossy();
    println!("OsString -> String (lossy): {}", lossy_string);
    
    println!("\nUSE CASES FOR OsStr/OsString:");
    println!("  • File system operations");
    println!("  • Environment variables");
    println!("  • Command-line arguments");
    println!("  • Interacting with OS APIs");
    
    // ========================================================================
    // 12. CStr AND CString (C-COMPATIBLE STRINGS)
    // ========================================================================
    section_header("12. CStr AND CString");
    
    /*
    WHAT ARE CStr/CString?
    - Compatible with C strings
    - Always null-terminated ('\0' at the end)
    - CStr = borrowed, CString = owned
    - Used for: FFI (Foreign Function Interface) with C code
    - NO interior null bytes allowed (except terminator)
    */
    
    // Create CString from &str
    let c_string = CString::new("Hello, C!").expect("CString::new failed");
    println!("CString: {:?}", c_string);
    
    // Get the raw pointer (for passing to C functions)
    let raw_ptr = c_string.as_ptr();
    println!("Raw pointer: {:p}", raw_ptr);
    
    // Get CStr from CString
    let c_str: &CStr = c_string.as_c_str();
    println!("CStr: {:?}", c_str);
    
    // CStr to &str
    match c_str.to_str() {
        Ok(s) => println!("CStr -> &str: {}", s),
        Err(e) => println!("CStr -> &str failed: {}", e),
    }
    
    // CString with embedded null (will fail!)
    let with_null = "Hello\0World";
    match CString::new(with_null) {
        Ok(_) => println!("\nCString with null: Success"),
        Err(e) => println!("\nCString with embedded null: Error - {}", e),
    }
    
    // Creating CStr from raw pointer (UNSAFE!)
    // This is just for demonstration - don't do this in real code
    // without proper safety guarantees
    println!("\nNOTE: Creating CStr from raw pointer requires unsafe block");
    println!("Example: unsafe {{ CStr::from_ptr(raw_ptr) }}");
    
    println!("\nUSE CASES FOR CStr/CString:");
    println!("  • Calling C functions from Rust (FFI)");
    println!("  • Passing strings to C libraries");
    println!("  • Receiving strings from C functions");
    
    // ========================================================================
    // 13. Path AND PathBuf (FILE SYSTEM PATHS)
    // ========================================================================
    section_header("13. Path AND PathBuf");
    
    /*
    WHAT ARE Path/PathBuf?
    - Specialized for file system paths
    - Path = borrowed slice, PathBuf = owned
    - Platform-agnostic operations
    - Internally uses OsStr/OsString
    */
    
    // Create Path from &str
    let path: &Path = Path::new("/usr/local/bin/rustc");
    println!("Path: {:?}", path);
    
    // Create PathBuf
    let mut path_buf = PathBuf::new();
    path_buf.push("/usr");
    path_buf.push("local");
    path_buf.push("bin");
    path_buf.push("rustc");
    println!("PathBuf: {:?}", path_buf);
    
    // Path operations
    println!("\nPath operations:");
    println!("  exists: {}", path.exists());
    println!("  is_file: {}", path.is_file());
    println!("  is_dir: {}", path.is_dir());
    println!("  parent: {:?}", path.parent());
    println!("  file_name: {:?}", path.file_name());
    println!("  extension: {:?}", path.extension());
    println!("  file_stem: {:?}", path.file_stem());
    
    // Path joining
    let base = Path::new("/home/user");
    let full = base.join("documents").join("file.txt");
    println!("\nJoined path: {:?}", full);
    
    // Path components
    println!("\nComponents:");
    for component in path.components() {
        println!("  {:?}", component);
    }
    
    // Path to String
    let path_str = path.to_string_lossy();
    println!("\nPath to String (lossy): {}", path_str);
    
    // ========================================================================
    // 14. STRING FORMATTING
    // ========================================================================
    section_header("14. STRING FORMATTING");
    
    let name = "Rust";
    let version = 1.75;
    let PI = 3.14159265;
    
    // Basic formatting
    println!("Basic: Hello, {}!", name);
    
    // Positional arguments
    println!("Positional: {0} is great! Love {0}!", name);
    
    // Named arguments
    println!("Named: {lang} version {ver}", lang=name, ver=version);
    
    // Width and alignment
    println!("Right (10): |{:10}|", name);   // Right align (default)
    println!("Left  (10): |{:<10}|", name);  // Left align
    println!("Center(10): |{:^10}|", name);  // Center align
    
    // Padding with specific character
    println!("Padded: |{:*>10}|", name);
    println!("Padded: |{:-<10}|", name);
    
    // Numbers formatting
    println!("\nNumbers:");
    println!("Default: {}", 42);
    println!("Binary:  {:b}", 42);
    println!("Octal:   {:o}", 42);
    println!("Hex:     {:x}", 42);
    println!("Hex cap: {:X}", 42);
    println!("With +:  {:+}", 42);
    println!("Zero pad: {:05}", 42);
    
    // Float formatting
    println!("\nFloats:");
    println!("Default: {}", PI);
    println!("2 dec:   {:.2}", PI);
    println!("Scientific: {:e}", PI);
    println!("0 width: {:010.2}", PI);
    
    // Debug formatting
    println!("\nDebug:");
    println!("&str debug: {:?}", name);
    println!("String debug: {:?}", name.to_string());
    
    // Display vs Debug
    struct Point { x: i32, y: i32 }
    impl std::fmt::Display for Point {
        fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "({}, {})", self.x, self.y)
        }
    }
    impl std::fmt::Debug for Point {
        fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "Point {{ x: {}, y: {} }}", self.x, self.y)
        }
    }
    let p = Point { x: 10, y: 20 };
    println!("Display: {}", p);
    println!("Debug:   {:?}", p);
    
    // ========================================================================
    // 15. TYPE CONVERSIONS BETWEEN STRING TYPES
    // ========================================================================
    section_header("15. TYPE CONVERSIONS");
    
    // &str <-> String
    let s: &str = "hello";
    let string: String = s.to_string();  // &str -> String
    let back: &str = &string;            // String -> &str (Deref)
    println!("&str -> String -> &str: {} -> {} -> {}", s, string, back);
    
    // String <-> Vec<u8>
    let s = String::from("hello");
    let bytes: Vec<u8> = s.into_bytes(); // String -> Vec<u8>
    let restored: String = String::from_utf8(bytes).unwrap(); // Vec<u8> -> String
    println!("\nString -> Vec<u8> -> String: {}", restored);
    
    // &str <-> &[u8]
    let s: &str = "hello";
    let bytes: &[u8] = s.as_bytes();  // &str -> &[u8]
    let restored: &str = std::str::from_utf8(bytes).unwrap(); // &[u8] -> &str
    println!("&str -> &[u8] -> &str: {} -> {:?} -> {}", s, bytes, restored);
    
    // String <-> OsString
    let s = String::from("hello");
    let os: OsString = s.into();  // String -> OsString
    let back: String = os.into_string().unwrap(); // OsString -> String
    println!("\nString -> OsString -> String: {}", back);
    
    // String <-> CString
    let s = String::from("hello");
    let cs = CString::new(s).unwrap();  // String -> CString
    let back: String = cs.into_string().unwrap(); // CString -> String
    println!("String -> CString -> String: {}", back);
    
    // String <-> PathBuf
    let s = String::from("/path/to/file");
    let pb: PathBuf = s.into();  // String -> PathBuf
    let back: String = pb.to_string_lossy().into_owned(); // PathBuf -> String
    println!("String -> PathBuf -> String: {}", back);
    
    // FromStr trait
    let parsed: i32 = "42".parse().unwrap();
    println!("\nParsing with FromStr: '42' -> {}", parsed);
    
    // ========================================================================
    // 16. COMMON STRING TRAITS
    // ========================================================================
    section_header("16. COMMON STRING TRAITS");
    
    let s = "Hello";
    
    // Display - user-facing format
    use std::fmt::Display;
    fn display_it<T: Display>(item: &T) {
        println!("Display: {}", item);
    }
    display_it(&s);
    
    // Debug - developer-facing format
    use std::fmt::Debug;
    fn debug_it<T: Debug>(item: &T) {
        println!("Debug: {:?}", item);
    }
    debug_it(&s);
    
    // Deref - automatic &String -> &str coercion
    let string = String::from("Hello");
    takes_str(&string); // Works because String derefs to str
    fn takes_str(s: &str) {
        println!("Deref coercion works: {}", s);
    }
    
    // AsRef<str>
    fn as_ref_str<S: AsRef<str>>(s: &S) {
        println!("AsRef<str>: {}", s.as_ref());
    }
    as_ref_str(&string);
    as_ref_str(&"literal");
    
    // Borrow<str>
    use std::borrow::Borrow;
    fn borrow_str<S: Borrow<str>>(s: &S) {
        println!("Borrow<str>: {}", s.borrow());
    }
    borrow_str(&string);
    borrow_str(&"literal");
    
    // ========================================================================
    // 17. STRING PERFORMANCE TIPS
    // ========================================================================
    section_header("17. STRING PERFORMANCE TIPS");
    
    // 1. Use &str for function parameters when possible
    fn process_text(text: &str) -> usize {  // Accepts both &str and &String
        text.len()
    }
    let owned = String::from("Hello");
    let borrowed = "World";
    println!("process_text(&String): {}", process_text(&owned));
    println!("process_text(&str): {}", process_text(borrowed));
    
    // 2. Pre-allocate capacity when building strings
    let mut builder = String::with_capacity(100);
    for i in 0..10 {
        builder.push_str(&format!("item {} ", i));
    }
    println!("\nPre-allocated (capacity: {}, len: {})", builder.capacity(), builder.len());
    
    // 3. Use format! instead of multiple + operators
    let a = "Hello";
    let b = "World";
    let c = "!";
    // Bad: let result = String::from(a) + " " + b + c;
    // Good:
    let result = format!("{} {}{}", a, b, c);
    println!("format! result: {}", result);
    
    // 4. Avoid unnecessary String allocations
    // Bad:
    fn bad_check(s: &str) -> bool {
        s.to_string().to_lowercase() == "hello"
    }
    // Good:
    fn good_check(s: &str) -> bool {
        s.eq_ignore_ascii_case("hello")
    }
    println!("\neq_ignore_ascii_case: {}", good_check("HELLO"));
    
    // 5. Use chars() vs bytes() appropriately
    let unicode = "日本語";
    println!("\nUnicode string: {}", unicode);
    println!("  chars().count(): {}", unicode.chars().count());
    println!("  bytes().len(): {}", unicode.bytes().len());
    
    // ========================================================================
    // 18. COMMON PITFALLS
    // ========================================================================
    section_header("18. COMMON PITFALLS");
    
    // Pitfall 1: String indexing with []
    // let s = "hello";
    // let c = s[0]; // ERROR! Cannot index into String with integer
    // Solution: use .chars().nth() or .as_bytes()[i]
    let s = "hello";
    let first_char = s.chars().next();
    let first_byte = s.as_bytes()[0];
    println!("First char: {:?}, First byte: {}", first_char, first_byte);
    
    // Pitfall 2: Slicing at non-UTF-8 boundaries
    let unicode = "你好";
    // let bad_slice = &unicode[0..1]; // PANIC! Middle of multi-byte char
    // Solution: use .char_indices() to find valid boundaries
    if let Some((end, _)) = unicode.char_indices().nth(1) {
        println!("Safe first char slice: '{}'", &unicode[0..end]);
    }
    
    // Pitfall 3: Forgetting that + takes ownership
    let a = String::from("Hello");
    let b = String::from(" World");
    // let c = a + &b;
    // println!("{}", a); // ERROR! a was moved
    // Solution: use format! or clone
    let c = format!("{}{}", a, b);
    println!("Both still valid: a='{}', b='{}', c='{}'", a, b, c);
    
    // Pitfall 4: Confusing len() with character count
    let emoji = "👨‍👩‍👧‍👦"; // Family emoji (multiple code points)
    println!("\nEmoji: {}", emoji);
    println!("  len() (bytes): {}", emoji.len());
    println!("  chars().count(): {}", emoji.chars().count());
    println!("  Note: Complex emoji may have multiple chars!");
    
    // ========================================================================
    // SUMMARY TABLE
    // ========================================================================
    section_header("SUMMARY TABLE");
    
    println!("┌─────────────┬──────────────┬─────────────┬─────────────────┐");
    println!("│ Type        │ Owned?       │ Mutable?    │ Use Case        │");
    println!("├─────────────┼──────────────┼─────────────┼─────────────────┤");
    println!("│ &str        │ Borrowed     │ No          │ Literals, params│");
    println!("│ String      │ Yes (heap)   │ Yes         │ Dynamic strings │");
    println!("│ OsStr       │ Borrowed     │ No          │ OS paths        │");
    println!("│ OsString    │ Yes (heap)   │ Yes         │ OS paths        │");
    println!("│ CStr        │ Borrowed     │ No          │ FFI with C      │");
    println!("│ CString     │ Yes (heap)   │ Yes         │ FFI with C      │");
    println!("│ Path        │ Borrowed     │ No          │ File paths      │");
    println!("│ PathBuf     │ Yes (heap)   │ Yes         │ File paths      │");
    println!("│ &[u8]       │ Borrowed     │ No          │ Raw bytes       │");
    println!("│ Vec<u8>     │ Yes (heap)   │ Yes         │ Raw bytes       │");
    println!("└─────────────┴──────────────┴─────────────┴─────────────────┘");
    
    println!("\n{}", "=".repeat(70));
    println!("                    END OF GUIDE");
    println!("{}".repeat(70));
}

// Helper function to print section headers
fn section_header(title: &str) {
    println!("\n{}", "─".repeat(70));
    println!("  {}", title);
    println!("{}", "─".repeat(70));
}