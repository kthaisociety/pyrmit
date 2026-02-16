import os
import base64
from ocr.detaljplan_ocr import MistralOCR

class MarkdownCreator:
    def __init__(self, api_key: str):
        self.ocr_processor = MistralOCR(api_key=api_key)
        # Create an images folder if it doesn't exist
        self.image_dir = "images"
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)

    def create_markdown(self, file_path: str) -> str:
        ocr_result = self.ocr_processor.main(file_path)
        markdown_content = self.convert_to_markdown(ocr_result)
        return markdown_content
    
    def save_base64_image(self, b64_string, filename):
        """Decodes base64 string and saves it as a file."""
        try:
            # Mistral sometimes includes the data header. We must strip it.
            # e.g., "data:image/jpeg;base64,/9j/4AAQSk..." -> "/9j/4AAQSk..."
            if "," in b64_string:
                b64_string = b64_string.split(",")[1]

            # Decode the string
            img_data = base64.b64decode(b64_string)
            
            image_path = os.path.join(self.image_dir, filename)
            with open(image_path, "wb") as f:
                f.write(img_data)
            return image_path
        except Exception as e:
            print(f"Error decoding image {filename}: {e}")
            return None

    def convert_to_markdown(self, ocr_result) -> str:
        full_doc_markdown = []

        # Ensure the image directory exists
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)

        for page_idx, page in enumerate(ocr_result.pages):
            page_md = page.markdown
            
            if hasattr(page, 'images') and page.images:
                for img in page.images:
                    # 1. Determine extension and filename
                    # We use .jpg because your snippet showed a JPEG header
                    img_ext = "jpg"  
                    filename = f"p{page_idx}_{img.id}.{img_ext}"
                    
                    # 2. Save the image to the 'images/' folder
                    saved_path = self.save_base64_image(img.image_base64, filename) 

                    if saved_path:
                        # 3. Format the path for the Markdown file
                        # This assumes the .md file is in the parent directory of /images
                        relative_path = f"{self.image_dir}/{filename}"
                        
                        # 4. Replace the Mistral placeholder (e.g., ![img_0])
                        # We use a simple replacement, but fallback to appending if placeholder isn't found
                        placeholder = f"![{img.id}]"
                        
                        if placeholder in page_md:
                            page_md = page_md.replace(placeholder, f"![{img.id}]({relative_path})")
                        else:
                            # Sometimes Mistral uses different patterns, check result prints for actual tag
                            page_md += f"\n\n![{img.id}]({relative_path})"
            
            full_doc_markdown.append(page_md)

        return "\n\n---\n\n".join(full_doc_markdown)
                    
# Usage remains the same
if __name__ == "__main__":
    api_key = os.environ["MISTRAL_API_KEY"]
    creator = MarkdownCreator(api_key=api_key)
    md_output = creator.create_markdown("chunking/data/kristineberg_etapp1.pdf")
    
    with open("output.md", "w", encoding="utf-8") as f:
        f.write(md_output)
    print("Done! Open output.md to see the text and images.")