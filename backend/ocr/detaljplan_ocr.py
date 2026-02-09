from mistralai import Mistral
import os

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

        signed_url = self.client.files.get_signed_url(file_id)
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