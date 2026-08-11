from __future__ import annotations

from datetime import datetime
from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import Point
from shapely.geometry.polygon import Polygon, orient

from .patterns import convert_to_one_layer_pattern_list, convert_to_two_layer_pattern_list


def show_coordinate(fig, ax, scatter):
    annot = ax.annotate(
        "",
        xy=(0, 0),
        xytext=(20, 20),
        textcoords="offset points",
        bbox=dict(boxstyle="round", fc="w"),
        arrowprops=dict(arrowstyle="->"),
    )
    annot.set_visible(False)

    def update_annot(ind):
        pos = scatter.get_offsets()[ind["ind"][0]]
        annot.xy = pos
        annot.set_text(f"({pos[0]:.2f}, {pos[1]:.2f})")

    def hover(event):
        vis = annot.get_visible()
        if event.inaxes == ax:
            cont, ind = scatter.contains(event)
            if cont:
                update_annot(ind)
                annot.set_visible(True)
                fig.canvas.draw_idle()
            elif vis:
                annot.set_visible(False)
                fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", hover)


def show_coorinate(fig, ax, scatter):
    """Backward-compatible misspelled alias."""
    return show_coordinate(fig, ax, scatter)


def plot_lattice(pos, show_coords=False):
    fig, ax = plt.subplots()
    scatter = ax.scatter(pos[:, 0], pos[:, 1])
    if show_coords:
        show_coordinate(fig, ax, scatter)
    plt.axis("equal")
    plt.show()


def plot_polygon(poly):
    x, y = zip(*poly)
    x += (x[0],)
    y += (y[0],)
    plt.plot(x, y, "b-")
    plt.fill(x, y, alpha=0.2)
    plt.axis("equal")
    plt.show()


def point_in_polygon(pos, polygon):
    poly = orient(Polygon(polygon), sign=1)
    return poly.contains(Point(pos))


def cut(points, polygon):
    poly = orient(Polygon(polygon), sign=1)
    mask = np.array([Point(point).within(poly) for point in points])
    return points[mask]


def plot_many(lst_points=None, lst_polyline=None, show_coords=True, noaxis=True):
    fig, ax = plt.subplots()
    scatter_holder = []
    annot_holder = []

    if lst_points is not None:
        for pos in convert_to_one_layer_pattern_list(lst_points):
            scatter = ax.scatter(pos[:, 0], pos[:, 1])
            scatter_holder.append(scatter)
            annot = ax.annotate(
                "",
                xy=(0, 0),
                xytext=(20, 20),
                textcoords="offset points",
                bbox=dict(boxstyle="round", fc="w"),
                arrowprops=dict(arrowstyle="->"),
            )
            annot.set_visible(False)
            annot_holder.append(annot)

    if lst_polyline is not None:
        for poly in convert_to_one_layer_pattern_list(lst_polyline):
            x, y = zip(*poly)
            x += (x[0],)
            y += (y[0],)
            ax.plot(x, y, "b-")

    def update_annot(ind, scatter):
        pos = scatter.get_offsets()[ind["ind"][0]]
        annot = annot_holder[scatter_holder.index(scatter)]
        annot.xy = pos
        annot.set_text(f"({pos[0]:.2f}, {pos[1]:.2f})")

    def hover(event):
        for scatter, annot in zip(scatter_holder, annot_holder):
            vis = annot.get_visible()
            if event.inaxes == scatter.axes:
                cont, ind = scatter.contains(event)
                if cont:
                    update_annot(ind, scatter)
                    annot.set_visible(True)
                    fig.canvas.draw_idle()
                elif vis:
                    annot.set_visible(False)
                    fig.canvas.draw_idle()

    if show_coords:
        fig.canvas.mpl_connect("motion_notify_event", hover)

    plt.axis("equal")
    if noaxis:
        plt.axis("off")
    plt.show()


def shift(pos, vector):
    if isinstance(pos, np.ndarray):
        return pos + vector
    return [shift(var, vector) for var in pos]


def rotate(pos, angle, origin=(0, 0)):
    if isinstance(pos, np.ndarray):
        shifted = pos - origin
        rotated = np.dot(
            shifted,
            np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]]),
        )
        return rotated + origin
    return [rotate(var, angle, origin) for var in pos]


def maketriangularlattice(period, size, draw=False, show_coords=True, angle=0.0, shift=(0, 0)):
    rows = size
    cols = size
    pos = np.array(
        [
            [(i + j % 2 / 2) * period, j * np.sqrt(3) / 2 * period]
            for i in range(cols)
            for j in range(rows)
        ]
    )
    pos -= np.mean(pos, axis=0)
    pos = rotate(pos, angle)
    pos += np.array(shift)
    if draw:
        plot_lattice(pos, show_coords)
    return pos


def makesquarelattice(period, size, draw=False, show_coords=True, angle=0.0, shift=(0, 0)):
    rows = size
    cols = size
    pos = np.array([[i * period, j * period] for i in range(cols) for j in range(rows)], dtype=float)
    pos -= np.mean(pos, axis=0)
    pos = np.dot(pos, np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]))
    pos += np.array(shift)
    if draw:
        plot_lattice(pos, show_coords)
    return pos


def find_closest_point_to_give_point(points, target):
    distances = np.linalg.norm(points - target, axis=1)
    return points[np.argmin(distances)]


def polygon(n, r, rotation=0):
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False) + rotation
    return np.column_stack((r * np.cos(angles), r * np.sin(angles)))


def find_point(points, main_index, secondary_index):
    valid_indices = ["top", "bottom", "left", "right"]
    if main_index not in valid_indices or secondary_index not in valid_indices:
        raise ValueError("main_index and secondary_index must be elements of [top, bottom, left, right]")

    if main_index == "top":
        primary_coord = 1
        sort_order = -1
    elif main_index == "bottom":
        primary_coord = 1
        sort_order = 1
    elif main_index == "left":
        primary_coord = 0
        sort_order = 1
    else:
        primary_coord = 0
        sort_order = -1

    sorted_points = points[np.argsort(points[:, primary_coord])[::sort_order]]
    primary_point = sorted_points[0]

    if secondary_index == "top":
        secondary_coord = 1
        secondary_sort_order = -1
    elif secondary_index == "bottom":
        secondary_coord = 1
        secondary_sort_order = 1
    elif secondary_index == "left":
        secondary_coord = 0
        secondary_sort_order = 1
    else:
        secondary_coord = 0
        secondary_sort_order = -1

    secondary_points = sorted_points[sorted_points[:, primary_coord] == primary_point[primary_coord]]
    sorted_points = secondary_points[np.argsort(secondary_points[:, secondary_coord])[::secondary_sort_order]]
    return sorted_points[0]


def find_largest_differences(array):
    return np.max(array[:, 0]) - np.min(array[:, 0]), np.max(array[:, 1]) - np.min(array[:, 1])


def flip_points(points, axis):
    if isinstance(points, np.ndarray):
        axis_vec = np.array(axis[1]) - np.array(axis[0])
        normal_vec = np.array([-axis_vec[1], axis_vec[0]])
        norm = np.dot(points, normal_vec) / np.dot(normal_vec, normal_vec)
        return points - 2 * (norm[:, np.newaxis] * normal_vec)
    return [flip_points(var, axis) for var in points]


def shift_along_axis(point, axis, dist):
    if isinstance(point, np.ndarray):
        distance = sum((axis[0][i] - axis[1][i]) ** 2 for i in range(len(axis[0]))) ** 0.5
        vector = [dist * (axis[1][i] - axis[0][i]) / distance for i in range(len(axis[0]))]
        return point + vector
    return [shift_along_axis(var, axis, dist) for var in point]


def find_boundary_for_N2_array(array, direction):
    if direction == "left":
        return np.min(array[:, 0])
    if direction == "right":
        return np.max(array[:, 0])
    if direction == "top":
        return np.max(array[:, 1])
    if direction == "bottom":
        return np.min(array[:, 1])
    raise ValueError("Invalid direction. Choose among left, right, top, bottom.")


def find_boundary_for_points(data, direction):
    data = convert_to_one_layer_pattern_list(data)
    if direction in ["left", "bottom"]:
        boundary_value = float("inf")
    elif direction in ["right", "top"]:
        boundary_value = -float("inf")
    else:
        raise ValueError("Invalid direction. Choose among left, right, top, bottom.")

    for array in data:
        current_boundary = find_boundary_for_N2_array(array, direction)
        if direction in ["left", "bottom"]:
            boundary_value = min(boundary_value, current_boundary)
        else:
            boundary_value = max(boundary_value, current_boundary)
    return boundary_value


def current_datetime_as_string():
    return datetime.now().strftime("%Y%m%d%H%M%S")


class Lattice:
    def __init__(self, period: float, outline: list[tuple[float, float]], orientation: float, lattice_type: str) -> None:
        self.period = period
        self.outline = [(self.period * x, self.period * y) for x, y in outline]
        self.orientation = orientation
        self.lattice_type = lattice_type
        self.points = self.get_points()

    def FreePattern(self, *args: list[tuple[float, float]]):
        return self.inner1_freepattern(self, *args)

    def PolygonPattern(self, n, r, theta, n2=None, r2=None, theta2=None):
        pattern1 = [
            (r * np.sin(2 * i * np.pi / n + np.deg2rad(theta)), r * np.cos(2 * i * np.pi / n + np.deg2rad(theta)))
            for i in range(n)
        ]
        if n2 is not None and r2 is not None and theta2 is not None:
            pattern2 = [
                (
                    r2 * np.sin(2 * i * np.pi / n2 + np.deg2rad(theta2)),
                    r2 * np.cos(2 * i * np.pi / n2 + np.deg2rad(theta2)),
                )
                for i in range(n2)
            ]
            return self.inner1_freepattern(self, pattern1, pattern2)
        return self.inner1_freepattern(self, pattern1)

    def get_points(self):
        poly = np.array(self.outline)
        shift_vector = np.mean(poly, axis=0)
        shifted_poly = poly - shift_vector
        large_enough_n = 5 * max(1, int(np.amax(shifted_poly) / self.period))

        if self.lattice_type in ["triangular", "tri", "t"]:
            pos = maketriangularlattice(
                period=self.period,
                size=large_enough_n,
                draw=False,
                show_coords=False,
                angle=self.orientation,
                shift=shift_vector,
            )
            return [cut(pos, poly)]

        if self.lattice_type in ["square", "sqr", "s"]:
            pos = makesquarelattice(
                period=self.period,
                size=large_enough_n,
                draw=False,
                show_coords=False,
                angle=self.orientation,
                shift=shift_vector,
            )
            return [cut(pos, poly)]

        if self.lattice_type in ["honeycomb", "hon", "hc", "h"]:
            pos1 = maketriangularlattice(period=self.period, size=large_enough_n, draw=False, show_coords=False)
            pos2 = maketriangularlattice(
                period=self.period,
                size=large_enough_n,
                draw=False,
                show_coords=False,
                shift=(self.period / 2, self.period / 2 / np.sqrt(3)),
            )

            def separate_operation(pos):
                pos = rotate(pos, self.orientation)
                pos = shift(pos, shift_vector)
                return cut(pos, poly)

            return [separate_operation(pos1), separate_operation(pos2)]

        raise ValueError("lattice_type must be triangular, square, or honeycomb.")

    def preview_lattice(self, show_outline=False):
        if show_outline:
            plot_many(self.points, [np.array(self.outline)], show_coords=True)
        else:
            plot_many(self.points, [], show_coords=True)

    def align_to_outline(
        self,
        main_index: Literal["top", "bottom", "left", "right"],
        secondary_index: Literal["top", "bottom", "left", "right"],
        sublattice=None,
    ):
        if self.lattice_type in ["honeycomb", "hon", "hc", "h"] and sublattice == 2:
            pos = self.points[1]
        else:
            pos = self.points[0]
        point_to_move = find_point(pos, main_index, secondary_index)
        target_position = find_point(np.array(self.outline), main_index, secondary_index)
        self.points = [shift(var, target_position - point_to_move) for var in self.points]

    def shift(self, vector):
        self.points = shift(self.points, vector)

    def rotate(self, angle, base_point):
        self.points = rotate(self.points, angle, base_point)

    def mirror(self, axis, keep_original=True, glide=0):
        reflected = shift_along_axis(flip_points(self.points, axis), axis, self.period * glide)
        if keep_original:
            self.points = [np.concatenate((self.points[i], reflected[i]), axis=0) for i in range(len(self.points))]
        else:
            self.points = reflected

    class inner1_freepattern:
        def __init__(self, outer_instance, *args: list[tuple[float, float]]) -> None:
            self.outer_instance = outer_instance
            self.args = [np.asarray(var, dtype=float) for var in args]
            self.pattern = self.get_pattern()

        def get_pattern(self):
            lattice_grids = self.outer_instance.points
            return [[self.args[i] + point for point in lattice_grids[i]] for i in range(len(self.args))]

        def shift(self, vector):
            self.pattern = shift(self.pattern, vector)

        def mirror(self, axis, keep_original=True, glide=0):
            reflected = shift_along_axis(flip_points(self.pattern, axis), axis, self.outer_instance.period * glide)
            if keep_original:
                self.pattern = [self.pattern[i] + reflected[i] for i in range(len(self.pattern))]
            else:
                self.pattern = reflected

        def truncate(self, polyline):
            result = []
            polyline = [(self.outer_instance.period * x, self.outer_instance.period * y) for x, y in polyline]
            for sublattice in self.pattern:
                sub = []
                for pats in sublattice:
                    center = np.mean(pats, axis=0)
                    if point_in_polygon(tuple(center), polyline):
                        sub.append(pats)
                result.append(sub)
            self.pattern = result

        def add_pattern(self, other_pattern):
            self.pattern += convert_to_two_layer_pattern_list(other_pattern)

        def preview_pattern(self, show_outline=False):
            pos = [inner_list for outer_list in self.pattern for inner_list in outer_list]
            if show_outline:
                plot_many([], pos + [np.array(self.outer_instance.outline)], show_coords=False)
            else:
                plot_many([], pos, show_coords=False)