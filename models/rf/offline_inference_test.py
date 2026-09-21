import json
import glob
import os

import joblib
import pandas as pd
from scipy.sparse import csr_matrix, hstack


# ============================================================
# Paths
# ============================================================

RF_DIR = os.getcwd()

DATA_ROOT = os.path.normpath(
    os.path.join(
        RF_DIR,
        "..",
        "..",
        "..",
        "QUT-DV25_Datasets",
        "QUT-DV25_Processed_Datasets",
    )
)


def find_csv(folder):
    files = glob.glob(os.path.join(DATA_ROOT, folder, "*.csv"))

    if not files:
        raise FileNotFoundError(
            f"No CSV found in: {os.path.join(DATA_ROOT, folder)}"
        )

    return files[0]


# ============================================================
# Load processed QUT-DV25 datasets
# ============================================================

filetop = pd.read_csv(find_csv("QUT-DV25_Filetop_Traces"))

install = pd.read_csv(find_csv("QUT-DV25_Install_Traces"))

opensnoop = pd.read_csv(find_csv("QUT-DV25_Opensnoop_Traces"))

pattern = pd.read_csv(find_csv("QUT-DV25_Pattern_Traces"))

syscall = pd.read_csv(find_csv("QUT-DV25_SysCall_Traces"))

tcp = pd.read_csv(find_csv("QUT-DV25_TCP_Traces"))


# ============================================================
# Select required columns
# ============================================================

F = filetop[
    [
        "Package_Name",
        "Read_Processes",
        "Write_Processes",
        "Total_Read_Data_Transfer",
        "Total_Write_Data_Transfer",
        "File_Access_Processes",
    ]
].rename(
    columns={
        "Total_Read_Data_Transfer": "Read_Data_Transfer",
        "Total_Write_Data_Transfer": "Write_Data_Transfer",
    }
)

I = install[
    [
        "Package_Name",
        "Total_Dependency_Count",
        "Total_Dependencies",
        "Direct_Dependency_Count",
        "Direct_Dependencies",
        "Indirect_Dependency_Count",
        "Indirect_Dependencies",
    ]
]

O = opensnoop[
    [
        "Package_Name",
        "Root_DIR_Installation",
        "Temporary_DIR_Installation",
        "Home_DIR_Installation",
        "User_Access",
        "Sys_Access",
        "Etc_DIR_Installation",
        "Other_DIR_Installation",
    ]
]

S = syscall[
    [
        "Package_Name",
        "IO_Operations",
        "File_Operations",
        "Network_Operations",
        "Time_Operations",
        "Security_Operations",
        "Process_Management_Operations",
    ]
]

T = tcp[
    [
        "Package_Name",
        "State_Transition",
        "Local_IP_Address_Access",
        "Remote_IP_Address_Access",
        "Local_Port_Access",
        "Remote_Port_Access",
    ]
]

P = pattern[
    ["Package_Name"] + [f"Pattern_{i}" for i in range(1, 11)]
]


# ============================================================
# Merge all six datasets
# ============================================================

df = (
    F.merge(I, on="Package_Name", how="inner")
    .merge(O, on="Package_Name", how="inner")
    .merge(S, on="Package_Name", how="inner")
    .merge(T, on="Package_Name", how="inner")
    .merge(P, on="Package_Name", how="inner")
)


# ============================================================
# Add Level
# ============================================================

levels = filetop[["Package_Name", "Level"]].drop_duplicates(
    "Package_Name"
)

df = df.merge(levels, on="Package_Name", how="left")


# ============================================================
# Rename processed columns to Tanzir's schema
# ============================================================

rename = {
    # Opensnoop
    "Root_DIR_Installation": "Root_DIR_Access",
    "Temporary_DIR_Installation": "Temp_DIR_Access",
    "Home_DIR_Installation": "Home_DIR_Access",
    "User_Access": "User_DIR_Access",
    "Sys_Access": "Sys_DIR_Access",
    "Etc_DIR_Installation": "Etc_DIR_Access",
    "Other_DIR_Installation": "Other_DIR_Access",

    # TCP
    "Local_IP_Address_Access": "Local_IPs_Access",
    "Remote_IP_Address_Access": "Remote_IPs_Access",

    # Installation numeric
    "Total_Dependency_Count": "Total_Dependencies",
    "Direct_Dependency_Count": "Direct_Dependencies",
    "Indirect_Dependency_Count": "Indirect_Dependencies",

    # SysCall
    "Process_Management_Operations": "Process_Operations",

    # Installation categorical lists
    "Total_Dependencies": "Total_Dependencies_List",
    "Direct_Dependencies": "Direct_Dependencies_List",
    "Indirect_Dependencies": "Indirect_Dependencies_List",
}

df = df.rename(columns=rename)


# ============================================================
# Load Tanzir schema
# ============================================================

with open(
    os.path.join(RF_DIR, "Combined_schema.json"),
    encoding="utf-8",
) as f:
    schema = json.load(f)

numeric = schema["numeric_columns"]
categorical = schema["categorical_columns"]


# ============================================================
# Verify schema
# ============================================================

missing = [
    column
    for column in numeric + categorical
    if column not in df.columns
]

if missing:
    raise ValueError(
        f"Missing schema columns: {missing}"
    )


# ============================================================
# Build numeric features
# ============================================================

X_numeric = df[numeric].fillna(0).astype(float)

X_numeric_sparse = csr_matrix(X_numeric.values)


# ============================================================
# Build categorical text
# ============================================================

categorical_text = (
    df[categorical]
    .fillna("")
    .astype(str)
    .agg(" ".join, axis=1)
)


# ============================================================
# Load model artifacts
# ============================================================

vectorizer = joblib.load(
    os.path.join(RF_DIR, "Combined_vectorizer.pkl")
)

scaler = joblib.load(
    os.path.join(RF_DIR, "Combined_scaler.pkl")
)

model = joblib.load(
    os.path.join(RF_DIR, "Combined_rf_model.pkl")
)


# ============================================================
# Vectorize categorical features
# ============================================================

X_categorical = vectorizer.transform(categorical_text)


# ============================================================
# Combine numeric + n-grams
# ============================================================

X = hstack(
    [
        X_numeric_sparse,
        X_categorical,
    ],
    format="csr",
)


# ============================================================
# Dimension check
# ============================================================

print("=" * 60)
print("QUT-DV25 OFFLINE DYSEC INFERENCE TEST")
print("=" * 60)

print(f"Packages after merge : {len(df)}")
print(f"Numeric columns      : {len(numeric)}")
print(f"Categorical columns  : {len(categorical)}")
print(f"N-gram features      : {X_categorical.shape[1]}")
print(f"Generated features   : {X.shape[1]}")
print(f"Model expects        : {model.n_features_in_}")

if X.shape[1] != model.n_features_in_:
    raise ValueError(
        f"\nFEATURE DIMENSION MISMATCH!\n"
        f"Generated: {X.shape[1]}\n"
        f"Expected : {model.n_features_in_}"
    )

print("\nDimension check: PASS")


# ============================================================
# Scale
# ============================================================

X_scaled = scaler.transform(X)


# ============================================================
# Predict
# ============================================================

prediction = model.predict(X_scaled)

probability = model.predict_proba(X_scaled)


# ============================================================
# Results
# ============================================================

result = pd.DataFrame(
    {
        "Package_Name": df["Package_Name"],
        "Actual_Level": df["Level"],
        "Prediction": prediction,
        "Verdict": [
            "MALICIOUS" if value == 1 else "BENIGN"
            for value in prediction
        ],
        "P_Benign": probability[:, 0],
        "P_Malicious": probability[:, 1],
    }
)


print("\nFirst 10 predictions:")
print(
    result.head(10).to_string(index=False)
)


print("\nActual labels:")
print(
    result["Actual_Level"]
    .value_counts()
    .sort_index()
)


print("\nPredictions:")
print(
    result["Prediction"]
    .value_counts()
    .sort_index()
)


# ============================================================
# Save results
# ============================================================

output = os.path.join(
    RF_DIR,
    "offline_inference_test_results.csv",
)

result.to_csv(
    output,
    index=False,
)

print(f"\nResults saved to:")
print(output)

print("\nTEST COMPLETE")