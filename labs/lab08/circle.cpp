#include <cstddef>

extern "C" std::size_t count_inside(
    const double* points, std::size_t n) {
    std::size_t count = 0;
    for (std::size_t i = 0; i < n; ++i) {
        double x = points[2*i];
        double y = points[2*i + 1];
        if (x*x + y*y < 1.0) {
            ++count;
        }
    }
    return count;
}
