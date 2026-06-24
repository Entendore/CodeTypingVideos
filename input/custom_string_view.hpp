#include <compare>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <limits>
#include <ostream>
#include <stdexcept>
#include <string>
#include <cassert>
#include <iostream>
#include <unordered_set>

namespace my {

// ============================================================================
// Basic String View - A non-owning reference to a contiguous sequence of chars
// ============================================================================
template <class CharT, class Traits = std::char_traits<CharT>>
class basic_string_view {
public:
    // ========================================================================
    // Type Aliases
    // ========================================================================
    using traits_type            = Traits;
    using value_type             = CharT;
    using pointer                = CharT*;
    using const_pointer          = const CharT*;
    using reference              = CharT&;
    using const_reference        = const CharT&;
    using const_iterator         = const CharT*;
    using iterator               = const_iterator;
    using const_reverse_iterator = std::reverse_iterator<const_iterator>;
    using reverse_iterator       = const_reverse_iterator;
    using size_type              = std::size_t;
    using difference_type        = std::ptrdiff_t;

    // ========================================================================
    // Constants
    // ========================================================================
    static constexpr size_type npos = static_cast<size_type>(-1);

    // ========================================================================
    // Constructors (all constexpr in C++23)
    // ========================================================================
    
    // Default constructor - empty view
    constexpr basic_string_view() noexcept = default;

    // Copy constructors (trivially copyable)
    constexpr basic_string_view(const basic_string_view&) noexcept = default;
    constexpr basic_string_view& operator=(const basic_string_view&) noexcept = default;

    // Construct from pointer and length
    constexpr basic_string_view(const CharT* str, size_type len) noexcept
        : data_(str), size_(len) {}

    // Construct from null-terminated C-string
    // C++23: Now fully constexpr even for non-empty strings
    constexpr basic_string_view(const CharT* str) noexcept
        : data_(str), size_(str ? Traits::length(str) : 0) {}

    // ========================================================================
    // Iterator Support
    // ========================================================================
    [[nodiscard]] constexpr const_iterator begin() const noexcept { return data_; }
    [[nodiscard]] constexpr const_iterator end() const noexcept { return data_ + size_; }
    [[nodiscard]] constexpr const_iterator cbegin() const noexcept { return begin(); }
    [[nodiscard]] constexpr const_iterator cend() const noexcept { return end(); }

    [[nodiscard]] constexpr const_reverse_iterator rbegin() const noexcept {
        return const_reverse_iterator(end());
    }
    [[nodiscard]] constexpr const_reverse_iterator rend() const noexcept {
        return const_reverse_iterator(begin());
    }
    [[nodiscard]] constexpr const_reverse_iterator crbegin() const noexcept {
        return const_reverse_iterator(cend());
    }
    [[nodiscard]] constexpr const_reverse_iterator crend() const noexcept {
        return const_reverse_iterator(cbegin());
    }

    // ========================================================================
    // Capacity
    // ========================================================================
    [[nodiscard]] constexpr size_type size() const noexcept { return size_; }
    [[nodiscard]] constexpr size_type length() const noexcept { return size_; }
    [[nodiscard]] constexpr size_type max_size() const noexcept {
        return (std::numeric_limits<size_type>::max)() / sizeof(CharT);
    }
    [[nodiscard]] constexpr bool empty() const noexcept { return size_ == 0; }

    // ========================================================================
    // Element Access
    // ========================================================================
    [[nodiscard]] constexpr const_reference operator[](size_type pos) const {
        return data_[pos];
    }

    [[nodiscard]] constexpr const_reference at(size_type pos) const {
        if (pos >= size_) {
            throw std::out_of_range("basic_string_view::at: pos out of range");
        }
        return data_[pos];
    }

    [[nodiscard]] constexpr const_reference front() const { return data_[0]; }
    [[nodiscard]] constexpr const_reference back() const { return data_[size_ - 1]; }
    [[nodiscard]] constexpr const_pointer data() const noexcept { return data_; }

    // ========================================================================
    // Modifiers
    // ========================================================================
    constexpr void remove_prefix(size_type n) noexcept {
        data_ += n;
        size_ -= n;
    }

    constexpr void remove_suffix(size_type n) noexcept {
        size_ -= n;
    }

    constexpr void swap(basic_string_view& other) noexcept {
        auto tmp = *this;
        *this = other;
        other = tmp;
    }

    // ========================================================================
    // String Operations
    // ========================================================================
    
    // Copy characters to buffer
    constexpr size_type copy(CharT* dest, size_type count, 
                             size_type pos = 0) const {
        if (pos > size_) {
            throw std::out_of_range("basic_string_view::copy: pos out of range");
        }
        const size_type rcount = std::min(count, size_ - pos);
        Traits::copy(dest, data_ + pos, rcount);
        return rcount;
    }

    // Create substring view
    constexpr basic_string_view substr(size_type pos = 0, 
                                       size_type count = npos) const {
        if (pos > size_) {
            throw std::out_of_range("basic_string_view::substr: pos out of range");
        }
        const size_type rcount = std::min(count, size_ - pos);
        return basic_string_view(data_ + pos, rcount);
    }

    // ========================================================================
    // Comparison Operations
    // ========================================================================
    constexpr int compare(basic_string_view sv) const noexcept {
        const size_type rlen = std::min(size_, sv.size_);
        int result = Traits::compare(data_, sv.data_, rlen);
        
        if (result != 0) return result;
        if (size_ == sv.size_) return 0;
        return (size_ < sv.size_) ? -1 : 1;
    }

    constexpr int compare(size_type pos1, size_type count1, 
                          basic_string_view sv) const {
        return substr(pos1, count1).compare(sv);
    }

    constexpr int compare(size_type pos1, size_type count1,
                          basic_string_view sv,
                          size_type pos2, size_type count2) const {
        return substr(pos1, count1).compare(sv.substr(pos2, count2));
    }

    constexpr int compare(const CharT* s) const {
        return compare(basic_string_view(s));
    }

    constexpr int compare(size_type pos1, size_type count1, 
                          const CharT* s) const {
        return substr(pos1, count1).compare(basic_string_view(s));
    }

    constexpr int compare(size_type pos1, size_type count1,
                          const CharT* s, size_type count2) const {
        return substr(pos1, count1).compare(basic_string_view(s, count2));
    }

    // ========================================================================
    // Prefix/Suffix Checks (C++20)
    // ========================================================================
    [[nodiscard]] constexpr bool starts_with(basic_string_view sv) const noexcept {
        return size_ >= sv.size_ && 
               Traits::compare(data_, sv.data_, sv.size_) == 0;
    }

    [[nodiscard]] constexpr bool starts_with(CharT c) const noexcept {
        return !empty() && Traits::eq(front(), c);
    }

    [[nodiscard]] constexpr bool starts_with(const CharT* s) const {
        return starts_with(basic_string_view(s));
    }

    [[nodiscard]] constexpr bool ends_with(basic_string_view sv) const noexcept {
        return size_ >= sv.size_ && 
               Traits::compare(data_ + size_ - sv.size_, sv.data_, sv.size_) == 0;
    }

    [[nodiscard]] constexpr bool ends_with(CharT c) const noexcept {
        return !empty() && Traits::eq(back(), c);
    }

    [[nodiscard]] constexpr bool ends_with(const CharT* s) const {
        return ends_with(basic_string_view(s));
    }

    // ========================================================================
    // Contains Check (C++23)
    // ========================================================================
    [[nodiscard]] constexpr bool contains(basic_string_view sv) const noexcept {
        return find(sv) != npos;
    }

    [[nodiscard]] constexpr bool contains(CharT c) const noexcept {
        return find(c) != npos;
    }

    [[nodiscard]] constexpr bool contains(const CharT* s) const {
        return find(s) != npos;
    }

    // ========================================================================
    // Find Operations
    // ========================================================================
    
    // Find substring
    [[nodiscard]] constexpr size_type find(basic_string_view sv, 
                                           size_type pos = 0) const noexcept {
        if (sv.empty()) return std::min(pos, size_);
        if (sv.size_ > size_ - pos) return npos;

        if constexpr (sizeof(CharT) == 1) {
            // Simple optimization for byte-sized characters
            if (sv.size_ == 1) {
                return find(sv[0], pos);
            }
        }

        for (size_type i = pos; i <= size_ - sv.size_; ++i) {
            if (Traits::compare(data_ + i, sv.data_, sv.size_) == 0) {
                return i;
            }
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find(CharT c, 
                                           size_type pos = 0) const noexcept {
        for (size_type i = pos; i < size_; ++i) {
            if (Traits::eq(data_[i], c)) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find(const CharT* s, size_type pos,
                                           size_type count) const {
        return find(basic_string_view(s, count), pos);
    }

    [[nodiscard]] constexpr size_type find(const CharT* s, 
                                           size_type pos = 0) const {
        return find(basic_string_view(s), pos);
    }

    // Reverse find substring
    [[nodiscard]] constexpr size_type rfind(basic_string_view sv,
                                            size_type pos = npos) const noexcept {
        if (sv.empty()) return std::min(pos, size_);
        if (sv.size_ > size_) return npos;

        const size_type start = std::min(pos, size_ - sv.size_);
        for (size_type i = start + 1; i-- > 0;) {
            if (Traits::compare(data_ + i, sv.data_, sv.size_) == 0) {
                return i;
            }
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type rfind(CharT c,
                                            size_type pos = npos) const noexcept {
        if (empty()) return npos;
        const size_type start = std::min(pos, size_ - 1);
        for (size_type i = start + 1; i-- > 0;) {
            if (Traits::eq(data_[i], c)) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type rfind(const CharT* s, size_type pos,
                                            size_type count) const {
        return rfind(basic_string_view(s, count), pos);
    }

    [[nodiscard]] constexpr size_type rfind(const CharT* s,
                                            size_type pos = npos) const {
        return rfind(basic_string_view(s), pos);
    }

    // Find first of any character
    [[nodiscard]] constexpr size_type find_first_of(basic_string_view sv,
                                                    size_type pos = 0) const noexcept {
        for (size_type i = pos; i < size_; ++i) {
            if (sv.find(data_[i]) != npos) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find_first_of(CharT c,
                                                    size_type pos = 0) const noexcept {
        return find(c, pos);
    }

    [[nodiscard]] constexpr size_type find_first_of(const CharT* s, size_type pos,
                                                    size_type count) const {
        return find_first_of(basic_string_view(s, count), pos);
    }

    [[nodiscard]] constexpr size_type find_first_of(const CharT* s,
                                                    size_type pos = 0) const {
        return find_first_of(basic_string_view(s), pos);
    }

    // Find last of any character
    [[nodiscard]] constexpr size_type find_last_of(basic_string_view sv,
                                                   size_type pos = npos) const noexcept {
        if (empty()) return npos;
        const size_type start = std::min(pos, size_ - 1);
        for (size_type i = start + 1; i-- > 0;) {
            if (sv.find(data_[i]) != npos) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find_last_of(CharT c,
                                                   size_type pos = npos) const noexcept {
        return rfind(c, pos);
    }

    [[nodiscard]] constexpr size_type find_last_of(const CharT* s, size_type pos,
                                                   size_type count) const {
        return find_last_of(basic_string_view(s, count), pos);
    }

    [[nodiscard]] constexpr size_type find_last_of(const CharT* s,
                                                   size_type pos = npos) const {
        return find_last_of(basic_string_view(s), pos);
    }

    // Find first not of any character
    [[nodiscard]] constexpr size_type find_first_not_of(basic_string_view sv,
                                                        size_type pos = 0) const noexcept {
        for (size_type i = pos; i < size_; ++i) {
            if (sv.find(data_[i]) == npos) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find_first_not_of(CharT c,
                                                        size_type pos = 0) const noexcept {
        for (size_type i = pos; i < size_; ++i) {
            if (!Traits::eq(data_[i], c)) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find_first_not_of(const CharT* s, size_type pos,
                                                        size_type count) const {
        return find_first_not_of(basic_string_view(s, count), pos);
    }

    [[nodiscard]] constexpr size_type find_first_not_of(const CharT* s,
                                                        size_type pos = 0) const {
        return find_first_not_of(basic_string_view(s), pos);
    }

    // Find last not of any character
    [[nodiscard]] constexpr size_type find_last_not_of(basic_string_view sv,
                                                       size_type pos = npos) const noexcept {
        if (empty()) return npos;
        const size_type start = std::min(pos, size_ - 1);
        for (size_type i = start + 1; i-- > 0;) {
            if (sv.find(data_[i]) == npos) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find_last_not_of(CharT c,
                                                       size_type pos = npos) const noexcept {
        if (empty()) return npos;
        const size_type start = std::min(pos, size_ - 1);
        for (size_type i = start + 1; i-- > 0;) {
            if (!Traits::eq(data_[i], c)) return i;
        }
        return npos;
    }

    [[nodiscard]] constexpr size_type find_last_not_of(const CharT* s, size_type pos,
                                                       size_type count) const {
        return find_last_not_of(basic_string_view(s, count), pos);
    }

    [[nodiscard]] constexpr size_type find_last_not_of(const CharT* s,
                                                       size_type pos = npos) const {
        return find_last_not_of(basic_string_view(s), pos);
    }

private:
    const_pointer data_{nullptr};
    size_type     size_{0};
};

// ============================================================================
// Type Aliases for Common Character Types
// ============================================================================
using string_view     = basic_string_view<char>;
using wstring_view    = basic_string_view<wchar_t>;
using u8string_view   = basic_string_view<char8_t>;
using u16string_view  = basic_string_view<char16_t>;
using u32string_view  = basic_string_view<char32_t>;

// ============================================================================
// Non-member Comparison Operators (C++20 spaceship operator)
// ============================================================================
template <class CharT, class Traits>
[[nodiscard]] constexpr bool operator==(basic_string_view<CharT, Traits> lhs,
                                        basic_string_view<CharT, Traits> rhs) noexcept {
    return lhs.compare(rhs) == 0;
}

template <class CharT, class Traits>
[[nodiscard]] constexpr std::strong_ordering operator<=>(
    basic_string_view<CharT, Traits> lhs,
    basic_string_view<CharT, Traits> rhs) noexcept {
    
    const int cmp = lhs.compare(rhs);
    if (cmp < 0)  return std::strong_ordering::less;
    if (cmp > 0)  return std::strong_ordering::greater;
    return std::strong_ordering::equal;
}

// Heterogeneous comparisons with C-strings
template <class CharT, class Traits>
[[nodiscard]] constexpr bool operator==(basic_string_view<CharT, Traits> lhs,
                                        const CharT* rhs) noexcept {
    return lhs == basic_string_view<CharT, Traits>(rhs);
}

template <class CharT, class Traits>
[[nodiscard]] constexpr bool operator==(const CharT* lhs,
                                        basic_string_view<CharT, Traits> rhs) noexcept {
    return basic_string_view<CharT, Traits>(lhs) == rhs;
}

template <class CharT, class Traits>
[[nodiscard]] constexpr std::strong_ordering operator<=>(
    basic_string_view<CharT, Traits> lhs,
    const CharT* rhs) noexcept {
    
    return lhs <=> basic_string_view<CharT, Traits>(rhs);
}

template <class CharT, class Traits>
[[nodiscard]] constexpr std::strong_ordering operator<=>(
    const CharT* lhs,
    basic_string_view<CharT, Traits> rhs) noexcept {
    
    return basic_string_view<CharT, Traits>(lhs) <=> rhs;
}

// ============================================================================
// Stream Output
// ============================================================================
template <class CharT, class Traits>
std::basic_ostream<CharT, Traits>& operator<<(
    std::basic_ostream<CharT, Traits>& os,
    basic_string_view<CharT, Traits> sv) {
    
    return os.write(sv.data(), static_cast<std::streamsize>(sv.size()));
}

} // namespace my

// ============================================================================
// Hash Specialization (for use with unordered containers)
// ============================================================================
template <class CharT, class Traits>
struct std::hash<my::basic_string_view<CharT, Traits>> {
    [[nodiscard]] size_t operator()(my::basic_string_view<CharT, Traits> sv) const noexcept {
        // FNV-1a hash algorithm
        if constexpr (sizeof(size_t) == 8) {
            size_t hash = 14695981039346656037ULL;
            for (CharT c : sv) {
                hash ^= static_cast<size_t>(c);
                hash *= 1099511628211ULL;
            }
            return hash;
        } else {
            size_t hash = 2166136261UL;
            for (CharT c : sv) {
                hash ^= static_cast<size_t>(c);
                hash *= 16777619UL;
            }
            return hash;
        }
    }
};

// ============================================================================
// User-Defined Literal Operators (C++23 allows constexpr)
// ============================================================================
namespace my::literals {

[[nodiscard]] constexpr my::string_view operator""sv(const char* str, std::size_t len) noexcept {
    return my::string_view(str, len);
}

[[nodiscard]] constexpr my::u8string_view operator""sv(const char8_t* str, std::size_t len) noexcept {
    return my::u8string_view(str, len);
}

[[nodiscard]] constexpr my::u16string_view operator""sv(const char16_t* str, std::size_t len) noexcept {
    return my::u16string_view(str, len);
}

[[nodiscard]] constexpr my::u32string_view operator""sv(const char32_t* str, std::size_t len) noexcept {
    return my::u32string_view(str, len);
}

[[nodiscard]] constexpr my::wstring_view operator""sv(const wchar_t* str, std::size_t len) noexcept {
    return my::wstring_view(str, len);
}

} // namespace my::literals

// ============================================================================
// Example Usage & Tests
// ============================================================================
int main() {
    using namespace my;
    using namespace my::literals;

    // ========================================================================
    // Construction
    // ========================================================================
    constexpr string_view sv1;                           // Empty
    constexpr string_view sv2{"Hello, World!"};         // From C-string
    constexpr string_view sv3{"Hello", 5};              // From pointer + length
    
    std::string str = "Another string";
    string_view sv4{str};                               // From std::string
    
    // User-defined literal
    constexpr auto sv5 = "literal view"sv;
    
    std::cout << "sv2: " << sv2 << "\n";
    std::cout << "sv3: " << sv3 << "\n";
    std::cout << "sv5: " << sv5 << "\n\n";

    // ========================================================================
    // Element Access
    // ========================================================================
    assert(sv2[0] == 'H');
    assert(sv2.front() == 'H');
    assert(sv2.back() == '!');
    assert(sv2.at(7) == 'W');
    
    // Bounds checking
    try {
        sv2.at(100);  // Throws
        assert(false);
    } catch (const std::out_of_range& e) {
        std::cout << "Caught: " << e.what() << "\n";
    }

    // ========================================================================
    // Iterators
    // ========================================================================
    std::cout << "Forward:  ";
    for (auto c : sv3) std::cout << c;
    std::cout << "\n";
    
    std::cout << "Reverse:  ";
    for (auto it = sv3.rbegin(); it != sv3.rend(); ++it) {
        std::cout << *it;
    }
    std::cout << "\n\n";

    // ========================================================================
    // Capacity
    // ========================================================================
    assert(!sv2.empty());
    assert(sv2.size() == 13);
    assert(sv2.length() == 13);
    assert(sv1.empty());
    std::cout << "sv2 size: " << sv2.size() << "\n";

    // ========================================================================
    // Modifiers
    // ========================================================================
    string_view sv6 = "Hello, World!";
    sv6.remove_prefix(7);
    assert(sv6 == "World!");
    
    string_view sv7 = "Hello, World!";
    sv7.remove_suffix(7);
    assert(sv7 == "Hello,");
    
    string_view a = "abc", b = "xyz";
    a.swap(b);
    assert(a == "xyz" && b == "abc");
    std::cout << "Modifiers work!\n\n";

    // ========================================================================
    // Substring
    // ========================================================================
    constexpr string_view text = "Hello, World!";
    constexpr auto sub = text.substr(7);
    assert(sub == "World!");
    constexpr auto sub2 = text.substr(0, 5);
    assert(sub2 == "Hello");
    std::cout << "Substring: " << sub << "\n\n";

    // ========================================================================
    // Comparisons (C++20 spaceship operator)
    // ========================================================================
    assert(string_view("abc") == string_view("abc"));
    assert(string_view("abc") != string_view("abd"));
    assert(string_view("abc") < string_view("abd"));
    assert(string_view("abd") > string_view("abc"));
    assert(string_view("abc") <= string_view("abc"));
    assert(string_view("abc") >= string_view("abc"));
    
    // Heterogeneous comparison with C-strings
    assert(string_view("hello") == "hello");
    assert("hello" == string_view("hello"));
    assert(string_view("abc") < "abd");
    std::cout << "Comparisons work!\n\n";

    // ========================================================================
    // starts_with / ends_with (C++20)
    // ========================================================================
    constexpr string_view url = "https://example.com/path";
    assert(url.starts_with("https://"));
    assert(url.starts_with('h'));
    assert(url.ends_with("/path"));
    assert(url.ends_with('h'));
    assert(!url.starts_with("http://"));
    assert(!url.ends_with(".org"));
    std::cout << "starts_with/ends_with work!\n\n";

    // ========================================================================
    // contains (C++23)
    // ========================================================================
    constexpr string_view sentence = "The quick brown fox jumps over the lazy dog";
    assert(sentence.contains("fox"));
    assert(sentence.contains('q'));
    assert(sentence.contains("lazy dog"));
    assert(!sentence.contains("cat"));
    assert(!sentence.contains('z'));  // 'z' is lowercase but not in sentence
    std::cout << "contains (C++23) works!\n\n";

    // ========================================================================
    // Find Operations
    // ========================================================================
    constexpr string_view haystack = "abracadabra";
    
    // find
    assert(haystack.find("abra") == 0);
    assert(haystack.find("abra", 1) == 7);
    assert(haystack.find('c') == 4);
    assert(haystack.find('z') == string_view::npos);
    
    // rfind
    assert(haystack.rfind("abra") == 7);
    assert(haystack.rfind('a') == 10);
    
    // find_first_of
    assert(haystack.find_first_of("xyz") == string_view::npos);
    assert(haystack.find_first_of("bcd") == 1);
    
    // find_last_of
    assert(haystack.find_last_of("bcd") == 8);
    
    // find_first_not_of
    assert(haystack.find_first_not_of("ab") == 2);
    
    // find_last_not_of
    assert(haystack.find_last_not_of("ab") == 8);
    std::cout << "Find operations work!\n\n";

    // ========================================================================
    // Copy
    // ========================================================================
    char buffer[6] = {};
    string_view source = "Hello";
    source.copy(buffer, 5);
    assert(std::string(buffer) == "Hello");
    std::cout << "Copy works: " << buffer << "\n\n";

    // ========================================================================
    // Use with Unordered Container (requires hash specialization)
    // ========================================================================
    std::unordered_set<string_view> words;
    words.insert("apple"sv);
    words.insert("banana"sv);
    words.insert("cherry"sv);
    
    assert(words.contains("apple"sv));
    assert(words.contains("banana"));
    assert(!words.contains("grape"));
    std::cout << "Unordered container works! Size: " << words.size() << "\n\n";

    // ========================================================================
    // Compile-Time Evaluation (C++23 enhancement)
    // ========================================================================
    constexpr bool compile_time_check = [] {
        string_view sv = "Hello, C++23!";
        return sv.starts_with("Hello") && 
               sv.ends_with("C++23!") &&
               sv.contains("++") &&
               sv.find("C++") != string_view::npos;
    }();
    assert(compile_time_check);
    std::cout << "Compile-time evaluation works!\n\n";

    // ========================================================================
    // Interoperability with std::string
    // ========================================================================
    std::string std_str = "Standard string";
    string_view view_from_std = std_str;
    assert(view_from_std == "Standard string");
    
    // Creating std::string from view
    std::string back_to_std(view_from_std);
    assert(back_to_std == std_str);
    std::cout << "std::string interoperability works!\n\n";

    std::cout << "=== All tests passed! ===\n";
    return 0;
}