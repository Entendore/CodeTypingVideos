def smallest_subarray_with_given_sum(s, arr):
    min_length = float('inf')
    window_sum = 0
    window_start = 0

    for window_end in range(0, len(arr)):
        # Add the next element to the window
        window_sum += arr[window_end]

        # Shrink the window as small as possible while the sum is still >= s
        while window_sum >= s:
            # Update the minimum length found so far
            current_length = window_end - window_start + 1
            min_length = min(min_length, current_length)
            
            # Remove the element at the start of the window and slide forward
            window_sum -= arr[window_start]
            window_start += 1
            
    return min_length if min_length != float('inf') else 0

# Test
target = 7
input_arr = [2, 1, 5, 2, 3, 2]
print(f"Smallest subarray length with sum >= {target}: {smallest_subarray_with_given_sum(target, input_arr)}")
# Output: 2 (The subarray is [5, 2])