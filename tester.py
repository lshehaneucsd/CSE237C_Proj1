import sys
import subprocess
import filecmp
import re
import os
import shutil
import glob

def extract_metrics(vari, combined_text):
    lat_match = re.search(
        r"Latency\s*\(cycles\).*?Type\s*\|\s*\n\s*\+[-+]+\+\s*\n\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
        combined_text,
        re.DOTALL
    )
    latency = lat_match.group(2) if lat_match else "NA"
    sample_ii = lat_match.group(4) if lat_match else "NA"

    tot_match = re.search(
        r"\|\s*Total\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
        combined_text
    )
    if tot_match:
        bram, dsp, ff, lut = tot_match.group(1), tot_match.group(2), tot_match.group(3), tot_match.group(4)
    else:
        bram = dsp = ff = lut = "NA"

    clk_match = re.search(r"\|\s*ap_clk\s*\|\s*[\d.]+\s*ns\|\s*([\d.]+)\s*ns", combined_text)
    
    throughput = "NA"
    if clk_match:
        try:
            clk_ns = float(clk_match.group(1))
            cycles = float(sample_ii) if sample_ii != "NA" else (float(latency) if latency != "NA" else 0)
            if clk_ns > 0 and cycles > 0:
                throughput = f"{1000.0 / (clk_ns * cycles):.3f}"
        except (ValueError, ZeroDivisionError):
            pass

    return {
        "Design": vari,
        "Latency": latency,
        "Sample II": sample_ii,
        "BRAM": bram,
        "DSP": dsp,
        "LUT": lut,
        "FF": ff,
        "Throughput (MHz)": throughput
    }

def format_markdown_table(rows):
    headers = ["Design", "Latency", "Sample II", "BRAM", "DSP", "LUT", "FF", "Throughput (MHz)"]
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join([":---"] * len(headers)) + " |"
    data_lines = []
    for r in rows:
        data_lines.append("| " + " | ".join(str(r.get(h, "NA")) for h in headers) + " |")
    return "\n".join([header_line, separator_line] + data_lines) + "\n"

def parse_existing_out(target_dir):
    rpt_files = glob.glob(os.path.join(target_dir, "*.rpt"))
    rows = []
    for rpt_path in sorted(rpt_files):
        vari = os.path.splitext(os.path.basename(rpt_path))[0]
        log_path = os.path.join(target_dir, f"{vari}.log")
        content = ""
        if os.path.exists(log_path):
            with open(log_path, "r", errors="ignore") as f:
                content += f.read() + "\n"
        with open(rpt_path, "r", errors="ignore") as f:
            content += f.read()
        row = extract_metrics(vari, content)
        rows.append(row)
        info_file = os.path.join(target_dir, f"{vari}.info")
        with open(info_file, "w") as f:
            f.write(format_markdown_table([row]))
    if rows:
        summary_file = os.path.join(target_dir, "results.md")
        table_str = format_markdown_table(rows)
        with open(summary_file, "w") as f:
            f.write(table_str)
        print(f"\nResults for {target_dir}:\n")
        print(table_str)
    return rows

def find_all_questions():
    q_set = set()
    if os.path.isdir("programs"):
        for entry in os.listdir("programs"):
            full = os.path.join("programs", entry)
            if os.path.isdir(full) and glob.glob(os.path.join(full, "fir*.*")):
                q_set.add(entry)
    ignore_dirs = {"out", "proj", "programs", ".git", ".gemini", ".agents", ".vscode"}
    for entry in os.listdir("."):
        if os.path.isdir(entry) and entry not in ignore_dirs:
            if glob.glob(os.path.join(entry, "fir*.*")):
                q_set.add(entry)
    return sorted(list(q_set))

def run_question(question, variations=None):
    q_dir = question
    if not os.path.exists(q_dir) and os.path.exists(os.path.join("programs", question)):
        q_dir = os.path.join("programs", question)

    proj_dir = "proj"
    out_dir = os.path.join("out", question)
    os.makedirs(out_dir, exist_ok=True)

    if not variations:
        files = glob.glob(os.path.join(q_dir, "fir_*.*"))
        var_set = set()
        for f in files:
            base = os.path.basename(f)
            m = re.match(r"fir_(.+?)\.(h|cpp)", base)
            if m:
                var_set.add(m.group(1))
        variations = sorted(list(var_set))

    print(f"\n==========================================")
    print(f"Running {question} with variations {variations}")
    print(f"==========================================")

    collected_rows = []

    for vari in variations:
        print(f"Running variation {vari}")
        for ext in ["h", "cpp"]:
            var_file = os.path.join(q_dir, f"fir_{vari}.{ext}")
            base_file = os.path.join(q_dir, f"fir.{ext}")
            dest_file = os.path.join(proj_dir, f"fir.{ext}")

            if os.path.exists(var_file):
                shutil.copy(var_file, dest_file)
            elif os.path.exists(base_file):
                shutil.copy(base_file, dest_file)

        subprocess.run(["touch", "fir.cpp"], cwd=proj_dir)
        test_process = subprocess.run(["make", "test"], cwd=proj_dir, capture_output=True, text=True)

        dat_path = os.path.join(proj_dir, "out.dat")
        gold_path = os.path.join(proj_dir, "out.gold.dat")

        if not filecmp.cmp(dat_path, gold_path, shallow=False):
            print(f"Variation {vari} failed golden output comparison")
            continue

        hls_process = subprocess.run(["make", "hls"], cwd=proj_dir, capture_output=True, text=True)
        hls_log = hls_process.stdout + hls_process.stderr

        report_process = subprocess.run(["make", "report"], cwd=proj_dir, capture_output=True, text=True)

        log_file = os.path.join(out_dir, f"{vari}.log")
        with open(log_file, "w") as f:
            f.write(test_process.stdout + test_process.stderr)
            f.write(hls_log)
            f.write(report_process.stdout + report_process.stderr)

        rpt_source = os.path.join(proj_dir, "fir_csynth.rpt")
        rpt_dest = os.path.join(out_dir, f"{vari}.rpt")

        rpt_text = ""
        if os.path.exists(rpt_source):
            shutil.move(rpt_source, rpt_dest)

        if os.path.exists(rpt_dest):
            with open(rpt_dest, "r") as f:
                rpt_text = f.read()

        combined_text = hls_log + "\n" + rpt_text
        row = extract_metrics(vari, combined_text)
        collected_rows.append(row)

        info_file = os.path.join(out_dir, f"{vari}.info")
        with open(info_file, "w") as f:
            f.write(format_markdown_table([row]))

    if collected_rows:
        summary_file = os.path.join(out_dir, "results.md")
        table_str = format_markdown_table(collected_rows)
        with open(summary_file, "w") as f:
            f.write(table_str)
        print("\n" + table_str)
    return collected_rows

def main():
    if len(sys.argv) < 2:
        print("Usage: python tester.py <question|all> [variation|--parse]")
        sys.exit(2)

    parse_mode = "--parse" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--parse"]

    question = args[0] if len(args) > 0 else "all"
    variations = [args[1]] if len(args) > 1 else []

    if parse_mode:
        if question == "all":
            for d in sorted(glob.glob(os.path.join("out", "*"))):
                if os.path.isdir(d):
                    parse_existing_out(d)
        else:
            target_out = os.path.join("out", question) if not question.startswith("out") else question
            parse_existing_out(target_out)
        return

    if question == "all":
        q_list = find_all_questions()
        print(f"Found questions to run: {q_list}")
        for q in q_list:
            run_question(q)
    else:
        run_question(question, variations)

if __name__ == "__main__":
    main()