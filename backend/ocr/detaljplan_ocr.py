from mistralai import Mistral
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ["MISTRAL_API_KEY"]

class MistralOCR:

    def __init__(self, api_key: str):

        self.client = Mistral(api_key=api_key)

    def upload_pdf(self, file_path: str):

        with open(file_path, "rb") as f:
            uploaded_pdf = self.client.files.upload(
                file={
                    "file_name": os.path.basename(file_path),
                    "content": f,
                },
                purpose="ocr"
            )  
        return uploaded_pdf
    
    def ocr(self, file_id: str):

        signed_url = self.client.files.get_signed_url(file_id=file_id)
        ocr_response = self.client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": signed_url.url,
            },
            table_format="html", # default is None
            # extract_header=True, # default is False
            # extract_footer=True, # default is False
            include_image_base64=False
        )

        return ocr_response

    def main(self, file_path: str):

        uploaded_pdf = self.upload_pdf(file_path)
        ocr_result = self.ocr(uploaded_pdf.id)
        return ocr_result
    
if __name__ == "__main__":
    ocr_processor = MistralOCR(api_key=api_key)
    result = ocr_processor.main("chunking/data/kristineberg_etapp1.pdf")
    print(result)