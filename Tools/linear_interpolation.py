from bisect import bisect_left

def lerp_with_bisect(x0, x1, y0, y1, x):
    # Create sorted x-list for bisect
    xs = [x0, x1]

    # Find insertion index of x
    idx = bisect_left(xs, x)

    # idx will be 1 when x is between x0 and x1
    # We interpolate between points 0 and 1
    i0 = idx - 1
    i1 = idx

    x_start = xs[i0]
    x_end = xs[i1]

    # Compute linear interpolation
    t = (x - x_start) / (x_end - x_start)
    y = y0 + t * (y1 - y0)

    return y


# Example usage
if __name__ == "__main__":
    print(lerp_with_bisect(0.28, 0.5, 0.25, 0.39, 0.30912898))  # Expected: 19.0

