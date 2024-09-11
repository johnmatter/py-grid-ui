#!/usr/bin/env python3.11
from abc import ABC, abstractmethod
import asyncio
import signal
import monome
from enum import Enum
import time
import random
import string

def generate_unique_id(existing_ids, length=6):
    while True:
        new_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if new_id not in existing_ids:
            return new_id

class PolygonType(Enum):
    TRIGGER = 1
    TOGGLE = 2
    SLIDER = 3

class Polygon(ABC):
    def __init__(self, points, type):
        self.points = points
        self.type = type
        self.state = 0
        self.flash_start = 0

    @abstractmethod
    def draw(self, buffer):
        pass

    def get_brightness(self):
        base_brightness = 3
        if self.state:
            elapsed = time.time() - self.flash_start
            if elapsed < 0.4:  # Flash for 0.4 seconds
                flash_brightness = int(15 - (elapsed / 0.1) * 4)  # Flash through 4 brightness levels
                return max(base_brightness, min(15, flash_brightness))
            else:
                return 15 if self.type == PolygonType.TOGGLE else base_brightness
        else:
            return base_brightness

class Rectangle(Polygon):
    def draw(self, buffer):
        brightness = self.get_brightness()
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                buffer.led_level_set(x, y, brightness)

class Triangle(Polygon):
    def draw(self, buffer):
        brightness = self.get_brightness()
        x1, y1 = self.points[0]
        x2, y2 = self.points[1]
        x3, y3 = self.points[2]
        min_x, max_x = min(x1, x2, x3), max(x1, x2, x3)
        min_y, max_y = min(y1, y2, y3), max(y1, y2, y3)
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                if self.point_inside(x, y):
                    buffer.led_level_set(x, y, brightness)

    def point_inside(self, x, y):
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
        b1 = sign((x, y), self.points[0], self.points[1]) < 0
        b2 = sign((x, y), self.points[1], self.points[2]) < 0
        b3 = sign((x, y), self.points[2], self.points[0]) < 0
        return (b1 == b2) and (b2 == b3)

class GridStudies(monome.GridApp):
    def __init__(self):
        super().__init__()
        self.width = 0
        self.height = 0
        self.reset()

    def reset(self):
        self.polygons = {}  # Dictionary to store polygons
        self.current_points = []

    def on_grid_ready(self):
        self.width = self.grid.width
        self.height = self.grid.height
        self.connected = True
        self.reset()
        self.draw()

    def on_grid_disconnect(self):
        self.connected = False
        self.reset()

    def on_grid_key(self, x, y, s):
        if s == 1:  # Key pressed
            self.current_points.append((x, y))
        else:  # Key released
            if len(self.current_points) == 2:
                self.create_polygon(self.create_rectangle)
            elif len(self.current_points) == 3:
                self.create_polygon(self.create_triangle)
            else:
                # Check if the point is inside any polygon
                for polygon_id, polygon in self.polygons.items():
                    if self.point_inside_polygon(x, y, polygon.points):
                        self.toggle_polygon(polygon_id)
                        break
            self.current_points = []
        self.draw()

    def create_polygon(self, create_func):
        new_polygon = create_func()
        if new_polygon and not self.polygons_overlap(new_polygon):
            new_id = generate_unique_id(self.polygons.keys())
            self.polygons[new_id] = new_polygon
        else:
            print("Cannot create overlapping polygon")

    def create_rectangle(self):
        x1, y1 = self.current_points[0]
        x2, y2 = self.current_points[1]
        points = [(min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))]
        return Rectangle(points, PolygonType.TRIGGER)

    def create_triangle(self):
        return Triangle(self.current_points, PolygonType.TRIGGER)

    def toggle_polygon(self, polygon_id):
        polygon = self.polygons[polygon_id]
        if polygon.type == PolygonType.TRIGGER:
            polygon.state = 1
        elif polygon.type == PolygonType.TOGGLE:
            polygon.state = 1 - polygon.state
        polygon.flash_start = time.time()

    def point_inside_polygon(self, x, y, points):
        if len(points) == 2:  # Rectangle
            x1, y1 = points[0]
            x2, y2 = points[1]
            return x1 <= x <= x2 and y1 <= y <= y2
        elif len(points) == 3:  # Triangle
            # Implement point-in-triangle check (e.g., barycentric coordinates)
            # This is a simplified version and may not work for all cases
            x1, y1 = points[0]
            x2, y2 = points[1]
            x3, y3 = points[2]
            def sign(p1, p2, p3):
                return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
            b1 = sign((x, y), points[0], points[1]) < 0
            b2 = sign((x, y), points[1], points[2]) < 0
            b3 = sign((x, y), points[2], points[0]) < 0
            return (b1 == b2) and (b2 == b3)
        return False

    def polygons_overlap(self, new_polygon):
        for existing_polygon in self.polygons.values():
            if self.check_overlap(new_polygon, existing_polygon):
                return True
        return False

    def check_overlap(self, poly1, poly2):
        # Check if any point of poly1 is inside poly2 or vice versa
        for point in poly1.points:
            if self.point_inside_polygon(point[0], point[1], poly2.points):
                return True
        for point in poly2.points:
            if self.point_inside_polygon(point[0], point[1], poly1.points):
                return True

        # Check if any edges intersect
        edges1 = self.get_edges(poly1.points)
        edges2 = self.get_edges(poly2.points)
        for edge1 in edges1:
            for edge2 in edges2:
                if self.lines_intersect(edge1, edge2):
                    return True

        return False

    def get_edges(self, points):
        edges = []
        for i in range(len(points)):
            edges.append((points[i], points[(i + 1) % len(points)]))
        return edges

    def lines_intersect(self, line1, line2):
        x1, y1 = line1[0]
        x2, y2 = line1[1]
        x3, y3 = line2[0]
        x4, y4 = line2[1]

        def ccw(A, B, C):
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

        return ccw((x1, y1), (x3, y3), (x4, y4)) != ccw((x2, y2), (x3, y3), (x4, y4)) and \
               ccw((x1, y1), (x2, y2), (x3, y3)) != ccw((x1, y1), (x2, y2), (x4, y4))

    def draw(self):
        if not self.connected:
            return
        
        buffer = monome.GridBuffer(self.width, self.height)

        # Draw polygons
        for polygon in self.polygons.values():
            polygon.draw(buffer)

        # Draw current selection
        for point in self.current_points:
            buffer.led_level_set(point[0], point[1], 15)

        buffer.render(self.grid)

    def cleanup(self):
        if self.connected:
            buffer = monome.GridBuffer(self.width, self.height)
            buffer.render(self.grid)
        print("\nCleaning up and exiting...")

"""
Main asynchronous function to set up and run the application.
Arguments: None
Returns: None
"""
async def main():
    """
    Callback function for when a serialosc device is added.
    Arguments:
        id (str): The device ID
        type (str): The device type
        port (int): The port number for the device
    Returns: None
    """
    def serialosc_device_added(id, type, port):
        print(f'connecting to {id} ({type}) on port {port}')
        asyncio.ensure_future(grid_studies.grid.connect('127.0.0.1', port))

    """
    Handles the SIGINT signal (Ctrl+C) to gracefully exit the program.
    Arguments: signum (int) - The signal number
               frame (frame object) - Current stack frame
    Returns: None
    """
    def signal_handler(signum, frame):
        print("\nCtrl+C pressed. Cleaning up...")
        grid_studies.cleanup()
        loop.stop()

    loop = asyncio.get_running_loop()
    grid_studies = GridStudies()

    serialosc = monome.SerialOsc()
    serialosc.device_added_event.add_handler(serialosc_device_added)

    await serialosc.connect()

    signal.signal(signal.SIGINT, signal_handler)

    try:
        await loop.create_future()
    finally:
        grid_studies.cleanup()

    await loop.create_future()

if __name__ == '__main__':
    asyncio.run(main())
