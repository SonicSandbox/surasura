import json
import base64
import os
import sys

# Mock Data Generator
def generate_mock_data(file_count=5, words_per_file=5000):
    progressive = []
    
    for i in range(file_count):
        filename = f"Massive_File_{i+1}.txt"
        words = []
        for j in range(words_per_file):
            words.append({
                "Word": f"Word_{i}_{j}",
                "Reading": "Reading",
                "Context 1": f"This is context sentence {j} for word {i}-{j}.",
                "Occurrences (Global)": 10,
                "Baseline %": 0, "Current %": 0, "New %": 0,
                "Known Count": 0, "Total Count": words_per_file
            })
            
        progressive.append({
            "filename": filename,
            "words": words,
            "total_words": words_per_file,
            "is_goal_content": (i % 2 == 0) # Alternate Goal Content
        })
        
    return {"progressive": progressive, "priority": [], "completed_files": []}

def create_test_html():
    # Read template
    with open("templates/web_app.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    data = generate_mock_data()
    json_str = json.dumps(data)
    
    # Inject
    html = html.replace("let globalData = null;", f"let globalData = {json_str};")
    
    with open("debug/perf_test.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    print("Created debug/perf_test.html with ~25,000 words.")

if __name__ == "__main__":
    create_test_html()
