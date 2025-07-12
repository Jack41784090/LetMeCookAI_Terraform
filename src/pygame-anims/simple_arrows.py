import pygame
import math
import sys
import os
import subprocess
from typing import Optional

# Initialize Pygame
pygame.init()

# Constants for 9:16 aspect ratio (YouTube Shorts)
WIDTH = 360
HEIGHT = 640
FPS = 60
RECORD_DURATION = 5  # seconds

# Colors
GOLD = (255, 215, 0)
ORANGE_RED = (255, 69, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
LIGHT_GOLD = (255, 245, 150)

class ArrowAnimation:
    def __init__(self, record=False):
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Arrow Animation - Recording" if record else "Arrow Animation")
        self.clock = pygame.time.Clock()
        self.time = 0
        self.record = record
        self.frame_count = 0
        self.max_frames = FPS * RECORD_DURATION if record else None
        
        # Initialize fonts - start with default font
        self.hindi_font = pygame.font.Font(None, 21)  # 25% smaller (28 * 0.75 = 21)
        self.hindi_works = False
        
        # Try to find a system font that supports Hindi/Devanagari
        hindi_fonts = [
            "mangal",           # Windows Hindi font
            "nirmalaui",        # Windows 10+ Hindi font
            "devanagari mt",    # macOS Hindi font
            "lohit devanagari", # Linux Hindi font
            "noto sans devanagari", # Google Noto font
            "arial unicode ms",  # Fallback with Unicode support
            "arial"             # Basic fallback
        ]
        
        # Find available fonts on system
        available_fonts = pygame.font.get_fonts()
        print("Available system fonts:", available_fonts[:10])  # Show first 10 fonts
        
        for font_name in hindi_fonts:
            if font_name.lower().replace(" ", "") in [f.lower().replace(" ", "") for f in available_fonts]:
                try:
                    test_font = pygame.font.SysFont(font_name, 21)  # 25% smaller
                    # Test if it can render Hindi
                    test_surface = test_font.render("हनुमान", True, (255, 255, 255))
                    if test_surface.get_width() > 10:  # Successfully rendered with actual width
                        self.hindi_font = test_font
                        self.hindi_works = True
                        print(f"✅ Using Hindi font: {font_name}")
                        break
                except Exception as e:
                    print(f"Failed to load {font_name}: {e}")
                    continue
        
        # Ultimate fallback - try any available font that might support Unicode
        if not self.hindi_works:
            print("Trying fallback fonts...")
            unicode_fonts = ['arial', 'calibri', 'segoeui', 'tahoma']
            for font_name in unicode_fonts:
                if font_name in available_fonts:
                    try:
                        test_font = pygame.font.SysFont(font_name, 21)  # 25% smaller
                        test_surface = test_font.render("हनुमान", True, (255, 255, 255))
                        if test_surface.get_width() > 10:
                            self.hindi_font = test_font
                            self.hindi_works = True
                            print(f"✅ Using fallback font: {font_name}")
                            break
                    except:
                        continue
        
        if not self.hindi_works:
            print("❌ No Hindi-capable font found, using English fallback")
        
        # Create smaller Hindi font for labels using the same working font
        if self.hindi_works:
            try:
                # Use the same font family that worked for main text
                font_name = self.hindi_font.get_name() if hasattr(self.hindi_font, 'get_name') else None
                if font_name:
                    self.hindi_font_small = pygame.font.SysFont(font_name, 18)
                else:
                    # Find the working font name from our test
                    for font_name in hindi_fonts:
                        if font_name.lower().replace(" ", "") in [f.lower().replace(" ", "") for f in available_fonts]:
                            try:
                                test_font = pygame.font.SysFont(font_name, 18)
                                test_surface = test_font.render("लाइक", True, (255, 255, 255))
                                if test_surface.get_width() > 5:
                                    self.hindi_font_small = test_font
                                    print(f"✅ Using Hindi font for labels: {font_name}")
                                    break
                            except:
                                continue
                    else:
                        self.hindi_font_small = pygame.font.Font(None, 18)
            except:
                self.hindi_font_small = pygame.font.Font(None, 18)
        else:
            self.hindi_font_small = pygame.font.Font(None, 18)
        
        # Regular fonts for English text
        self.font_large = pygame.font.Font(None, 36)
        self.font_medium = pygame.font.Font(None, 28)
        self.font_small = pygame.font.Font(None, 24)
        
        # Create frames directory if recording
        if self.record:
            self.frames_dir = "frames"
            if not os.path.exists(self.frames_dir):
                os.makedirs(self.frames_dir)
            print(f"Recording {RECORD_DURATION} seconds at {FPS} FPS...")
        
    def draw_arrow(self, start_x, start_y, end_x, end_y, color):
        """Draw an animated arrow pointing from start to end position"""
        # Calculate arrow direction and length
        dx = end_x - start_x
        dy = end_y - start_y
        length = math.sqrt(dx*dx + dy*dy)
        
        if length == 0:
            return
            
        # Normalize direction
        dx /= length
        dy /= length
        
        # Animation offset for pulsing effect
        pulse = math.sin(self.time * 0.3) * 10
        animated_end_x = end_x + dx * pulse
        animated_end_y = end_y + dy * pulse
        
        # Draw arrow shaft
        shaft_thickness = 1
        pygame.draw.line(self.screen, color, (int(start_x), int(start_y)), 
                        (int(animated_end_x), int(animated_end_y)), shaft_thickness)
        
        # Draw arrowhead
        arrowhead_size = 25
        angle = math.atan2(dy, dx)
        
        # Arrowhead points
        arrow_point1_x = animated_end_x - arrowhead_size * math.cos(angle - 0.3)
        arrow_point1_y = animated_end_y - arrowhead_size * math.sin(angle - 0.3)
        arrow_point2_x = animated_end_x - arrowhead_size * math.cos(angle + 0.3)
        arrow_point2_y = animated_end_y - arrowhead_size * math.sin(angle + 0.3)
        
        # Draw filled arrowhead
        arrow_points = [
            (int(animated_end_x), int(animated_end_y)),
            (int(arrow_point1_x), int(arrow_point1_y)),
            (int(arrow_point2_x), int(arrow_point2_y))
        ]
        pygame.draw.polygon(self.screen, color, arrow_points)
        
        # Add glow effect
        glow_intensity = int(50 + 25 * math.sin(self.time * 0.25))
        glow_color = (
            min(255, color[0] + glow_intensity//2), 
            min(255, color[1] + glow_intensity//2), 
            min(255, color[2] + glow_intensity//2)
        )
        pygame.draw.line(self.screen, glow_color, (int(start_x), int(start_y)), 
                       (int(animated_end_x), int(animated_end_y)), shaft_thickness + 4)
    
    def create_video(self):
        """Create MP4 video from saved frames using FFmpeg"""
        if not self.record:
            return
            
        print("Creating video from frames...")
        ffmpeg_command = [
            "ffmpeg", "-y",  # -y to overwrite existing file
            "-framerate", str(FPS),
            "-i", os.path.join(self.frames_dir, "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            "arrow_animation.mp4"
        ]
        
        try:
            result = subprocess.run(ffmpeg_command, capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ Video created successfully: arrow_animation.mp4")
                # Clean up frames directory
                print("Cleaning up frame files...")
                for filename in os.listdir(self.frames_dir):
                    if filename.endswith('.png'):
                        os.remove(os.path.join(self.frames_dir, filename))
                os.rmdir(self.frames_dir)
                print("✅ Cleanup complete!")
            else:
                print("❌ FFmpeg error:", result.stderr)
                print("Manual command:")
                print(f"ffmpeg -framerate {FPS} -i frames/frame_%04d.png -c:v libx264 -pix_fmt yuv420p -r {FPS} arrow_animation.mp4")
        except FileNotFoundError:
            print("❌ FFmpeg not found. Please install FFmpeg and add it to your PATH.")
            print("Manual command:")
            print(f"ffmpeg -framerate {FPS} -i frames/frame_%04d.png -c:v libx264 -pix_fmt yuv420p -r {FPS} arrow_animation.mp4")
    
    def save_frame(self):
        """Save current frame as PNG"""
        if self.record:
            filename = os.path.join(self.frames_dir, f"frame_{self.frame_count:04d}.png")
            pygame.image.save(self.screen, filename)
    
    def draw_text_labels(self):
        """Draw Hindi blessing text and bilingual labels"""
        # Create glowing text effect
        glow_intensity = int(20 + 10 * math.sin(self.time * 0.15))
        glow_color = (255, 215 + glow_intensity, 0)
        
        if self.hindi_works:
            # Main Hindi blessing at the top with glow effect
            hindi_text = "हनुमान का आशीर्वाद पाने के लिए लाइक और सब्सक्राइब करें"
            
            # Main text
            blessing_surface = self.font_medium.render(hindi_text, True, GOLD)
            blessing_rect = blessing_surface.get_rect(center=(WIDTH//2, 50))
            
            # Create text that fits within screen width
            if blessing_rect.width > WIDTH - 20:
                # Split into two lines if too wide
                line1 = "हनुमान का आशीर्वाद पाने के लिए"
                line2 = "लाइक और सब्सक्राइब करें"
                
                line1_surface = self.hindi_font.render(line1, True, glow_color)
                line2_surface = self.hindi_font.render(line2, True, glow_color)
                
                line1_rect = line1_surface.get_rect(center=(WIDTH//2, 40))
                line2_rect = line2_surface.get_rect(center=(WIDTH//2, 65))
                
                self.screen.blit(line1_surface, line1_rect)
                self.screen.blit(line2_surface, line2_rect)
            else:
                blessing_surface = self.hindi_font.render(hindi_text, True, glow_color)
                blessing_rect = blessing_surface.get_rect(center=(WIDTH//2, 50))
                self.screen.blit(blessing_surface, blessing_rect)
            
            # Hindi labels
            like_hindi = self.hindi_font_small.render("लाइक", True, LIGHT_GOLD)
            sub_hindi = self.hindi_font_small.render("सब्सक्राइब", True, (255, 100, 50))
        else:
            # Fallback to English
            english_text = "Like and Subscribe for Hanuman's Blessing"
            blessing_surface = self.font_medium.render(english_text, True, glow_color)
            blessing_rect = blessing_surface.get_rect(center=(WIDTH//2, 50))
            self.screen.blit(blessing_surface, blessing_rect)
            
            # English labels
            like_hindi = self.font_small.render("LIKE", True, LIGHT_GOLD)
            sub_hindi = self.font_small.render("SUBSCRIBE", True, (255, 100, 50))
        
        # "Like" labels next to golden arrow (English + Hindi/English)
        like_eng = self.font_small.render("LIKE", True, GOLD)
        
        # Position near the golden arrow
        arrow_right_y = HEIGHT // 3
        like_eng_rect = like_eng.get_rect(center=(WIDTH//2 - 60, arrow_right_y - 30))
        like_hindi_rect = like_hindi.get_rect(center=(WIDTH//2 - 60, arrow_right_y - 10))
        
        self.screen.blit(like_eng, like_eng_rect)
        self.screen.blit(like_hindi, like_hindi_rect)
        
        # "Subscribe" labels next to red arrow (English + Hindi/English)
        sub_eng = self.font_small.render("SUBSCRIBE", True, ORANGE_RED)
        
        # Position near the orange-red arrow
        arrow_down_x = WIDTH * 2 // 3
        sub_eng_rect = sub_eng.get_rect(center=(arrow_down_x + 60, HEIGHT//2))
        sub_hindi_rect = sub_hindi.get_rect(center=(arrow_down_x + 60, HEIGHT//2 + 20))
        
        self.screen.blit(sub_eng, sub_eng_rect)
        self.screen.blit(sub_hindi, sub_hindi_rect)
    
    def run(self):
        """Main animation loop"""
        running = True
        
        while running:
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
            
            # Stop recording after max frames
            if self.record and self.max_frames and self.frame_count >= self.max_frames:
                print(f"Recording complete! {self.frame_count} frames saved.")
                self.create_video()
                running = False
            
            # Update animation timer
            self.time += 1
            
            # Clear screen with black background
            self.screen.fill(BLACK)
            
            # Draw the two arrows
            # Arrow pointing right (at one-third height)
            arrow_right_y = HEIGHT // 3
            arrow_right_start_x = 75
            arrow_right_end_x = WIDTH - 100
            self.draw_arrow(arrow_right_start_x, arrow_right_y, 
                          arrow_right_end_x, arrow_right_y, GOLD)
            
            # Arrow pointing down (at two-thirds width)
            arrow_down_x = WIDTH * 2 // 3
            arrow_down_start_y = 250
            arrow_down_end_y = HEIGHT - 100
            self.draw_arrow(arrow_down_x, arrow_down_start_y, 
                          arrow_down_x, arrow_down_end_y, ORANGE_RED)
            
            # Draw text labels
            self.draw_text_labels()
            
            # Save frame if recording
            self.save_frame()
            
            # Update display
            pygame.display.flip()
            self.clock.tick(FPS)
            
            # Increment frame counter
            if self.record:
                self.frame_count += 1
        
        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    # Check command line arguments for recording mode
    record_mode = len(sys.argv) > 1 and sys.argv[1] == "--record"
    
    if record_mode:
        print("Starting recording mode...")
    else:
        print("Running animation (use --record to save video)")
        print("Press ESC to exit")
    
    # Create and run the animation
    animation = ArrowAnimation(record=record_mode)
    animation.run()
