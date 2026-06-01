from services.bibliographic import process_folder
from services.persistence import OUTPUT_FOLDER, save_master_dataframe


def main():
    df, errors = process_folder()
    output_file = save_master_dataframe(df)

    for error in errors:
        print(f"ERROR en {error['Archivo']}")
        print(error["Error"])

    print("\n====================================")
    print("EXTRACCIÓN COMPLETADA")
    print(f"Total artículos: {len(df)}")
    print(f"Archivo: {output_file}")
    print(f"Errores: {len(errors)}")
    print(f"Carpeta de salida: {OUTPUT_FOLDER}")
    print("====================================")


if __name__ == "__main__":
    main()
