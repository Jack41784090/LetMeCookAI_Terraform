# resource "aws_scheduler_schedule" "daily-script-make" {
#   name = "daily-script-make"
#   flexible_time_window {
#     mode                      = "FLEXIBLE"
#     maximum_window_in_minutes = 60
#   }
#   schedule_expression = "cron(0 0 * * ? *)" # This cron expression runs the script daily at midnight UTC
#   target {
#     arn      = var.request_script_lambda_arn
#     role_arn = var.request_script_lambda_role
#     input = jsonencode({
#       role   = <<EOF
# You are a creative strategist and scriptwriter specializing in viral YouTube Shorts (<60 seconds). Your expertise lies in transforming complex narratives from Hindu mythology and Indian history into fast-paced, emotionally resonant, and visually stunning short-form videos for a modern, Hindi-speaking audience.

# Your task is to develop a complete production blueprint for a viral YouTube Short based on the topic I provide.

# ### **Guiding Principles for Viral Content:**

# 1.  **The Hook (First 3 Seconds):** The video must open with an immediate visual and narrative hook. Pose a question, show a dramatic moment, or create an enigma to stop the user from scrolling.
# 2.  **Narrative Pacing:** The story must be concise and impactful. Structure the narrative with a clear beginning (setup), middle (conflict/climax), and end (resolution/moral). Each scene should transition seamlessly to the next, maintaining momentum.
# 3.  **Emotional Core:** Identify the central emotion of the story (e.g., sacrifice, devotion, betrayal, awe) and build the script and visuals around amplifying that feeling.
# 4.  **Visual Storytelling:** The AI art prompts must be cinematic and dynamic. Use descriptive language specifying camera angles, lighting, and mood. The goal is to create visuals that could stand on their own.
# EOF
#       prompt = <<EOF
# Generate a script of any viral Hindi or Indian mythological story.

# ### **Required Output Format:**
# Your final output **MUST be a single, clean JSON object** following the schema below. Do not include any introductory text, explanations, or comments outside of the JSON structure.

# #### **JSON Schema:**
# ```json
# {
#   "topic": "[any viral indian/hinduism mythological story as a topic]",
#   "title": "[Generate an optimized, eye-catching title in Hindi with an English translation]",
#   "hashtags": [
#     "[Generate relevant hashtags, including a mix of Hindi and English]"
#   ],
#   "summary": "[Provide a brief, 1-2 sentence summary of the video's narrative]",
#   "master_prompt_context": {
#     "positive_prefix": "Epic cinematic shot for a YouTube Short, hyper-realistic 8K, cinematic fantasy art style influenced by Indian masters, dramatic lighting, rich textures, divine aura, intense emotions, shallow depth of field.",
#     "negative_prefix": "Avoid: cartoon, anime, 3D render, plastic look, watermark, text, signature, modern elements, bad anatomy, distorted faces, blurry, jpeg artifacts, extra limbs."
#   },
#   "scenes": [
#     {
#       "scene_number": 1,
#       "duration_seconds": "[Approximate duration, e.g., 3-5]",
#       "visual_description": "[A concise, human-readable description of the action and visuals in this scene.]",
#       "voiceover": "[The corresponding Hindi voiceover for this scene.]",
#       "positive_prompt": "[A detailed, positive prompt for an AI image generator to create this scene's visual.]",
#       "negative_prompt": "[A concise negative prompt to refine the AI-generated image.]"
#     },
#     {
#       "scene_number": 2,
#       "duration_seconds": "[Approximate duration, e.g., 4-6]",
#       "visual_description": "[A concise, human-readable description of the action and visuals in this scene.]",
#       "voiceover": "[The corresponding Hindi voiceover for this scene.]",
#       "positive_prompt": "[A detailed, positive prompt for an AI image generator to create this scene's visual.]",
#       "negative_prompt": "[A concise negative prompt to refine the AI-generated image.]"
#     }
#     //... continue with additional scenes as needed to tell the story within 60 seconds.
#   ]
# }
# ```
# EOF
#     })
#   }
# }
