import os
import time
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics import TextAnalyticsClient
from tqdm import tqdm
from docx import Document
import PyPDF2
import pypandoc

def split_text(text, max_length):
    """Divide el texto en partes más pequeñas de longitud máxima `max_length`."""
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]

def read_txt(file_path):
    """Lee el contenido de un archivo .txt."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def read_docx(file_path):
    """Lee el contenido de un archivo .docx."""
    doc = Document(file_path)
    return '\n'.join([para.text for para in doc.paragraphs])

def read_pdf(file_path):
    """Lee el contenido de un archivo .pdf."""
    with open(file_path, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
        return text

def read_doc(file_path):
    """Convierte y lee el contenido de un archivo .doc."""
    output = pypandoc.convert_file(file_path, 'docx')
    return read_docx(output)

def read_file(file_path):
    """Determina el tipo de archivo y lee su contenido."""
    _, file_extension = os.path.splitext(file_path)
    if file_extension == '.txt':
        return read_txt(file_path)
    elif file_extension == '.docx':
        return read_docx(file_path)
    elif file_extension == '.pdf':
        return read_pdf(file_path)
    elif file_extension == '.doc':
        return read_doc(file_path)
    else:
        raise ValueError(f"Formato de archivo no soportado: {file_extension}")

def main():
    try:
        # Obtener configuraciones
        load_dotenv()
        ai_endpoint = os.getenv('AI_SERVICE_ENDPOINT')
        ai_key = os.getenv('AI_SERVICE_KEY')

        # Verificar que las variables de entorno se hayan cargado correctamente
        if not ai_endpoint or not ai_key:
            raise ValueError("Las variables de entorno AI_SERVICE_ENDPOINT y AI_SERVICE_KEY deben estar configuradas.")

        # Crear cliente usando endpoint y key
        credential = AzureKeyCredential(ai_key)
        ai_client = TextAnalyticsClient(endpoint=ai_endpoint, credential=credential)

        # Solicitar al usuario qué resultados desea visualizar
        print("Seleccione los resultados que desea visualizar (separados por comas):")
        print("1. Palabras clave del documento")
        print("2. Entidades")
        print("3. Enlaces")
        print("4. Resumen abstractivo")
        user_choices = input("Ingrese los números de las opciones seleccionadas: ").split(',')

        # Analizar cada archivo de texto en la carpeta reviews
        reviews_folder = 'reviews'
        for file_name in os.listdir(reviews_folder):
            if file_name == '.DS_Store':
                continue  # Omitir archivos del sistema

            file_path = os.path.join(reviews_folder, file_name)
            try:
                # Leer el contenido del archivo
                print('\n-------------\n' + file_name)
                text = read_file(file_path)
                print('\n' + text)

                # Dividir el texto en partes más pequeñas si es necesario
                max_length = 5120
                text_parts = split_text(text, max_length)

                combined_text = ""
                all_phrases = set()
                all_entities = set()
                all_linked_entities = set()
                sentiments = []

                # Mostrar animación de procesamiento
                with tqdm(total=len(text_parts), desc="procesando solicitud...") as pbar:
                    for part in text_parts:
                        # Obtener idioma
                        detected_language = ai_client.detect_language(documents=[part])[0]
                        language = detected_language.primary_language.iso6391_name

                        # Obtener sentimiento
                        sentiment_analysis = ai_client.analyze_sentiment(documents=[part])[0]
                        sentiments.append(sentiment_analysis.sentiment)

                        # Obtener frases clave si el usuario lo solicitó
                        if '1' in user_choices:
                            phrases = ai_client.extract_key_phrases(documents=[part])[0].key_phrases
                            all_phrases.update(phrases)

                        # Obtener entidades si el usuario lo solicitó
                        if '2' in user_choices:
                            entities = ai_client.recognize_entities(documents=[part])[0].entities
                            all_entities.update((entity.text, entity.category) for entity in entities)

                        # Obtener entidades vinculadas si el usuario lo solicitó
                        if '3' in user_choices:
                            linked_entities = ai_client.recognize_linked_entities(documents=[part])[0].entities
                            all_linked_entities.update((linked_entity.name, linked_entity.url) for linked_entity in linked_entities)

                        # Combinar el texto de todas las partes
                        combined_text += part + " "

                        # Actualizar barra de progreso
                        pbar.update(1)
                        time.sleep(0.1)  # Simular tiempo de procesamiento

                # Obtener resumen abstractivo del texto combinado si el usuario lo solicitó
                summary = ""
                if '4' in user_choices:
                    poller = ai_client.begin_abstract_summary(
                        documents=[combined_text],
                        language=language,
                        display_name="Resumen abstractivo",
                        sentence_count=20  # Aumentar el número de oraciones para un resumen más detallado
                    )
                    abstract_summary_results = poller.result()
                    for result in abstract_summary_results:
                        if result.kind == "AbstractiveSummarization":
                            paragraphs = []
                            current_paragraph = []
                            for summary in result.summaries:
                                current_paragraph.append(summary.text)
                                if len(current_paragraph) >= 3:  # Agrupar oraciones en párrafos de 3 oraciones
                                    paragraphs.append(" ".join(current_paragraph))
                                    current_paragraph = []
                            if current_paragraph:
                                paragraphs.append(" ".join(current_paragraph))
                            summary = "\n\n".join(paragraphs)  # Unir párrafos con doble salto de línea
                        elif result.is_error:
                            print("...Is an error with code '{}' and message '{}'".format(
                                result.error.code, result.error.message
                            ))

                # Mostrar resultados combinados
                print("\n-------------\nResultados para el documento: " + file_name)
                print("\nIdioma detectado: {}".format(detected_language.primary_language.name))
                print("\nSentimiento: {}".format(max(set(sentiments), key=sentiments.count)))  # Sentimiento más común
                if '1' in user_choices and all_phrases:
                    print("\nPalabras clave del documento:")
                    for phrase in all_phrases:
                        print('\t{}'.format(phrase))
                if '2' in user_choices and all_entities:
                    print("\nEntidades:")
                    for entity, category in all_entities:
                        print('\t{} ({})'.format(entity, category))
                if '3' in user_choices and all_linked_entities:
                    print("\nEnlaces:")
                    for name, url in all_linked_entities:
                        print('\t{} ({})'.format(name, url))
                if '4' in user_choices:
                    print("\nResumen abstractivo:")
                    print(f"{summary}\n")

            except (UnicodeDecodeError, ValueError) as e:
                print(f"Error al leer el archivo {file_name}: {e}")

    except Exception as ex:
        print(ex)

if __name__ == "__main__":
    main()