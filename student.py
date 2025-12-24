import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


DB_FILE = "students.db"


# -------------------------
# Database Layer
# -------------------------
class StudentDB:
    def __init__(self, db_path: str = DB_FILE):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            address TEXT,
            class_name TEXT NOT NULL
        );
        """)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            term_name TEXT NOT NULL,
            gpa REAL NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            UNIQUE(student_id, term_name)
        );
        """)
        self.conn.commit()

    def add_student(self, student_id: str, name: str, address: str, class_name: str):
        self.conn.execute(
            "INSERT INTO students (student_id, name, address, class_name) VALUES (?, ?, ?, ?)",
            (student_id.strip(), name.strip(), address.strip(), class_name.strip())
        )
        self.conn.commit()

    def delete_student(self, student_row_id: int):
        self.conn.execute("DELETE FROM students WHERE id = ?", (student_row_id,))
        self.conn.commit()

    def list_classes(self):
        cur = self.conn.execute("SELECT DISTINCT class_name FROM students ORDER BY class_name")
        return [r[0] for r in cur.fetchall()]

    def list_students_by_class(self, class_name: str):
        cur = self.conn.execute(
            "SELECT id, student_id, name, address, class_name FROM students WHERE class_name = ? ORDER BY name",
            (class_name,)
        )
        return cur.fetchall()

    def search_students_by_class_like(self, class_name: str, q: str):
        like = f"%{q.strip()}%"
        cur = self.conn.execute(
            "SELECT id, student_id, name, address, class_name FROM students "
            "WHERE class_name = ? AND (name LIKE ? OR student_id LIKE ?) "
            "ORDER BY name",
            (class_name, like, like)
        )
        return cur.fetchall()

    def get_student(self, student_row_id: int):
        cur = self.conn.execute(
            "SELECT id, student_id, name, address, class_name FROM students WHERE id = ?",
            (student_row_id,)
        )
        return cur.fetchone()

    def add_term_grade(self, student_row_id: int, term_name: str, gpa: float):
        self.conn.execute(
            "INSERT INTO terms (student_id, term_name, gpa) VALUES (?, ?, ?)",
            (student_row_id, term_name.strip(), float(gpa))
        )
        self.conn.commit()

    def list_terms_for_student(self, student_row_id: int):
        cur = self.conn.execute(
            "SELECT term_name, gpa FROM terms WHERE student_id = ? ORDER BY id",
            (student_row_id,)
        )
        return cur.fetchall()

    def delete_term(self, student_row_id: int, term_name: str):
        self.conn.execute(
            "DELETE FROM terms WHERE student_id = ? AND term_name = ?",
            (student_row_id, term_name)
        )
        self.conn.commit()

    def class_stats(self, class_name: str):
        """
        Return per-student latest average GPA and overall aggregates.
        """
        # Per-student average GPA across terms
        cur = self.conn.execute("""
            SELECT s.id, s.name, AVG(t.gpa) as avg_gpa, COUNT(t.id) as term_count
            FROM students s
            LEFT JOIN terms t ON t.student_id = s.id
            WHERE s.class_name = ?
            GROUP BY s.id
            ORDER BY s.name
        """, (class_name,))
        rows = cur.fetchall()

        gpas = [r[2] for r in rows if r[2] is not None]
        overall = {
            "count_students": len(rows),
            "count_with_terms": len(gpas),
            "avg_gpa": sum(gpas) / len(gpas) if gpas else None,
            "min_gpa": min(gpas) if gpas else None,
            "max_gpa": max(gpas) if gpas else None,
        }
        return rows, overall


# -------------------------
# GUI Layer
# -------------------------
class StudentSystemApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Student System (SQLite + Tkinter)")
        self.geometry("1200x700")
        self.minsize(1100, 650)

        self.db = StudentDB()

        # State
        self.selected_class = tk.StringVar(value="")
        self.search_text = tk.StringVar(value="")
        self.selected_student_row_id = None  # internal DB row id

        self._build_ui()
        self._refresh_classes()
        self._set_default_class()

    def _build_ui(self):
        # Layout: left (dashboard list), right (details + chart)
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        root.columnconfigure(0, weight=2)
        root.columnconfigure(1, weight=3)
        root.rowconfigure(0, weight=1)

        left = ttk.Frame(root)
        right = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right.grid(row=0, column=1, sticky="nsew")

        # -------------------------
        # Left: Class filter + student list + add/delete
        # -------------------------
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)

        header = ttk.Label(left, text="Dashboard", font=("Segoe UI", 16, "bold"))
        header.grid(row=0, column=0, sticky="w")

        filter_row = ttk.Frame(left)
        filter_row.grid(row=1, column=0, sticky="ew", pady=(10, 5))
        filter_row.columnconfigure(1, weight=1)

        ttk.Label(filter_row, text="Class:").grid(row=0, column=0, sticky="w")
        self.class_combo = ttk.Combobox(filter_row, textvariable=self.selected_class, state="readonly")
        self.class_combo.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self.class_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_students())

        ttk.Button(filter_row, text="Refresh", command=self._refresh_all).grid(row=0, column=2, sticky="e")

        search_row = ttk.Frame(left)
        search_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        search_row.columnconfigure(1, weight=1)

        ttk.Label(search_row, text="Search:").grid(row=0, column=0, sticky="w")
        search_entry = ttk.Entry(search_row, textvariable=self.search_text)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        search_entry.bind("<KeyRelease>", lambda e: self._refresh_students())
        ttk.Button(search_row, text="Clear", command=self._clear_search).grid(row=0, column=2)

        # Student list
        self.student_tree = ttk.Treeview(left, columns=("student_id", "name"), show="headings", height=18)
        self.student_tree.heading("student_id", text="Student ID")
        self.student_tree.heading("name", text="Name")
        self.student_tree.column("student_id", width=120, anchor="w")
        self.student_tree.column("name", width=240, anchor="w")
        self.student_tree.grid(row=3, column=0, sticky="nsew")
        self.student_tree.bind("<<TreeviewSelect>>", self._on_student_select)

        # Buttons
        btn_row = ttk.Frame(left)
        btn_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        ttk.Button(btn_row, text="Add Student", command=self._open_add_student).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(btn_row, text="Delete Student", command=self._delete_selected_student).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        # -------------------------
        # Right: Student details + terms + chart
        # -------------------------
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self.details_title = ttk.Label(right, text="Student Details", font=("Segoe UI", 16, "bold"))
        self.details_title.grid(row=0, column=0, sticky="w")

        self.details_box = ttk.LabelFrame(right, text="Profile", padding=10)
        self.details_box.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        self.details_box.columnconfigure(1, weight=1)

        self.lbl_student_id = ttk.Label(self.details_box, text="Student ID: -")
        self.lbl_name = ttk.Label(self.details_box, text="Name: -")
        self.lbl_address = ttk.Label(self.details_box, text="Address: -")
        self.lbl_class = ttk.Label(self.details_box, text="Class: -")

        self.lbl_student_id.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.lbl_name.grid(row=0, column=1, sticky="w")
        self.lbl_address.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(4, 0))
        self.lbl_class.grid(row=1, column=1, sticky="w", pady=(4, 0))

        # Middle: Terms + add term
        mid = ttk.Frame(right)
        mid.grid(row=2, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=2)
        mid.columnconfigure(1, weight=3)
        mid.rowconfigure(0, weight=1)

        terms_frame = ttk.LabelFrame(mid, text="Term Grades", padding=10)
        terms_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        terms_frame.rowconfigure(1, weight=1)
        terms_frame.columnconfigure(0, weight=1)

        add_term_frame = ttk.Frame(terms_frame)
        add_term_frame.grid(row=0, column=0, sticky="ew")
        add_term_frame.columnconfigure(1, weight=1)

        ttk.Label(add_term_frame, text="Term:").grid(row=0, column=0, sticky="w")
        self.term_name_var = tk.StringVar(value="")
        ttk.Entry(add_term_frame, textvariable=self.term_name_var).grid(row=0, column=1, sticky="ew", padx=(6, 6))

        ttk.Label(add_term_frame, text="GPA:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.term_gpa_var = tk.StringVar(value="")
        ttk.Entry(add_term_frame, textvariable=self.term_gpa_var).grid(row=1, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))

        ttk.Button(add_term_frame, text="Add Term", command=self._add_term).grid(row=0, column=2, rowspan=2, sticky="ns")

        self.term_tree = ttk.Treeview(terms_frame, columns=("term", "gpa"), show="headings", height=10)
        self.term_tree.heading("term", text="Term")
        self.term_tree.heading("gpa", text="GPA")
        self.term_tree.column("term", width=160, anchor="w")
        self.term_tree.column("gpa", width=80, anchor="center")
        self.term_tree.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        ttk.Button(terms_frame, text="Delete Selected Term", command=self._delete_selected_term).grid(row=2, column=0, sticky="ew", pady=(10, 0))

        # Chart + class stats
        chart_frame = ttk.LabelFrame(mid, text="Performance", padding=10)
        chart_frame.grid(row=0, column=1, sticky="nsew")
        chart_frame.rowconfigure(1, weight=1)
        chart_frame.columnconfigure(0, weight=1)

        self.stats_label = ttk.Label(chart_frame, text="Select a class/student to view statistics.")
        self.stats_label.grid(row=0, column=0, sticky="w")

        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("Term GPA Trend")
        self.ax.set_xlabel("Term")
        self.ax.set_ylabel("GPA")

        self.canvas = FigureCanvasTkAgg(self.figure, master=chart_frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.grid(row=1, column=0, sticky="nsew", pady=(10, 0))

        # Initial empty chart
        self._plot_empty()

    # -------------------------
    # UI Actions
    # -------------------------
    def _refresh_all(self):
        self._refresh_classes()
        self._refresh_students()
        self._refresh_class_stats()
        self._clear_student_details()

    def _refresh_classes(self):
        classes = self.db.list_classes()
        self.class_combo["values"] = classes

    def _set_default_class(self):
        vals = self.class_combo["values"]
        if vals:
            self.selected_class.set(vals[0])
            self._refresh_students()
            self._refresh_class_stats()

    def _clear_search(self):
        self.search_text.set("")
        self._refresh_students()

    def _refresh_students(self):
        class_name = self.selected_class.get().strip()
        if not class_name:
            return

        q = self.search_text.get().strip()

        for item in self.student_tree.get_children():
            self.student_tree.delete(item)

        if q:
            rows = self.db.search_students_by_class_like(class_name, q)
        else:
            rows = self.db.list_students_by_class(class_name)

        for (row_id, student_id, name, address, class_name) in rows:
            # store internal row_id in iid
            self.student_tree.insert("", "end", iid=str(row_id), values=(student_id, name))

        self._refresh_class_stats()

    def _refresh_class_stats(self):
        class_name = self.selected_class.get().strip()
        if not class_name:
            return

        per_student, overall = self.db.class_stats(class_name)
        if overall["avg_gpa"] is None:
            text = f"Class '{class_name}': {overall['count_students']} students (no term grades yet)."
        else:
            text = (
                f"Class '{class_name}': {overall['count_students']} students; "
                f"{overall['count_with_terms']} have grades. "
                f"Avg GPA: {overall['avg_gpa']:.2f}, Min: {overall['min_gpa']:.2f}, Max: {overall['max_gpa']:.2f}"
            )
        self.stats_label.config(text=text)

    def _on_student_select(self, _event):
        selection = self.student_tree.selection()
        if not selection:
            return
        row_id = int(selection[0])
        self.selected_student_row_id = row_id
        self._load_student_details(row_id)

    def _load_student_details(self, student_row_id: int):
        st = self.db.get_student(student_row_id)
        if not st:
            return
        _, student_id, name, address, class_name = st

        self.lbl_student_id.config(text=f"Student ID: {student_id}")
        self.lbl_name.config(text=f"Name: {name}")
        self.lbl_address.config(text=f"Address: {address or '-'}")
        self.lbl_class.config(text=f"Class: {class_name}")

        self._refresh_terms(student_row_id)
        self._plot_student(student_row_id)

    def _clear_student_details(self):
        self.selected_student_row_id = None
        self.lbl_student_id.config(text="Student ID: -")
        self.lbl_name.config(text="Name: -")
        self.lbl_address.config(text="Address: -")
        self.lbl_class.config(text="Class: -")

        for item in self.term_tree.get_children():
            self.term_tree.delete(item)
        self._plot_empty()

    def _open_add_student(self):
        dialog = tk.Toplevel(self)
        dialog.title("Add Student")
        dialog.geometry("420x260")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frm = ttk.Frame(dialog, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        sid_var = tk.StringVar()
        name_var = tk.StringVar()
        addr_var = tk.StringVar()
        class_var = tk.StringVar(value=self.selected_class.get().strip() or "")

        ttk.Label(frm, text="Student ID:").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=sid_var).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Name:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=name_var).grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Address:").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=addr_var).grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Class:").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=class_var).grid(row=3, column=1, sticky="ew", pady=6)

        def on_add():
            sid = sid_var.get().strip()
            nm = name_var.get().strip()
            cl = class_var.get().strip()
            ad = addr_var.get().strip()

            if not sid or not nm or not cl:
                messagebox.showerror("Validation", "Student ID, Name, and Class are required.")
                return

            try:
                self.db.add_student(sid, nm, ad, cl)
            except sqlite3.IntegrityError:
                messagebox.showerror("Duplicate", "Student ID already exists. Please use a unique Student ID.")
                return
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add student:\n{e}")
                return

            dialog.destroy()
            self._refresh_classes()
            self.selected_class.set(cl)
            self._refresh_students()

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        ttk.Button(btns, text="Cancel", command=dialog.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(btns, text="Add", command=on_add).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _delete_selected_student(self):
        selection = self.student_tree.selection()
        if not selection:
            messagebox.showinfo("Delete", "Please select a student to delete.")
            return

        row_id = int(selection[0])
        st = self.db.get_student(row_id)
        if not st:
            return

        _, student_id, name, _, _ = st
        if not messagebox.askyesno("Confirm Delete", f"Delete student '{name}' (ID: {student_id})?\nThis also deletes all term grades."):
            return

        try:
            self.db.delete_student(row_id)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete:\n{e}")
            return

        self._refresh_students()
        self._clear_student_details()

    def _refresh_terms(self, student_row_id: int):
        for item in self.term_tree.get_children():
            self.term_tree.delete(item)

        terms = self.db.list_terms_for_student(student_row_id)
        for term_name, gpa in terms:
            self.term_tree.insert("", "end", iid=term_name, values=(term_name, f"{gpa:.2f}"))

    def _add_term(self):
        if self.selected_student_row_id is None:
            messagebox.showinfo("Add Term", "Select a student first.")
            return

        term_name = self.term_name_var.get().strip()
        gpa_str = self.term_gpa_var.get().strip()

        if not term_name or not gpa_str:
            messagebox.showerror("Validation", "Term and GPA are required.")
            return

        try:
            gpa = float(gpa_str)
            if gpa < 0.0 or gpa > 4.0:
                messagebox.showerror("Validation", "GPA must be between 0.0 and 4.0.")
                return
        except ValueError:
            messagebox.showerror("Validation", "GPA must be a number (e.g., 3.50).")
            return

        try:
            self.db.add_term_grade(self.selected_student_row_id, term_name, gpa)
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate", "That term already exists for this student. Use a different term name.")
            return
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add term:\n{e}")
            return

        self.term_name_var.set("")
        self.term_gpa_var.set("")
        self._refresh_terms(self.selected_student_row_id)
        self._plot_student(self.selected_student_row_id)
        self._refresh_class_stats()

    def _delete_selected_term(self):
        if self.selected_student_row_id is None:
            messagebox.showinfo("Delete Term", "Select a student first.")
            return

        selection = self.term_tree.selection()
        if not selection:
            messagebox.showinfo("Delete Term", "Select a term to delete.")
            return

        term_name = selection[0]
        if not messagebox.askyesno("Confirm", f"Delete term '{term_name}'?"):
            return

        try:
            self.db.delete_term(self.selected_student_row_id, term_name)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete term:\n{e}")
            return

        self._refresh_terms(self.selected_student_row_id)
        self._plot_student(self.selected_student_row_id)
        self._refresh_class_stats()

    # -------------------------
    # Plotting
    # -------------------------
    def _plot_empty(self):
        self.ax.clear()
        self.ax.set_title("Term GPA Trend")
        self.ax.set_xlabel("Term")
        self.ax.set_ylabel("GPA")
        self.ax.set_ylim(0, 4)
        self.canvas.draw()

    def _plot_student(self, student_row_id: int):
        terms = self.db.list_terms_for_student(student_row_id)

        self.ax.clear()
        self.ax.set_title("Term GPA Trend")
        self.ax.set_xlabel("Term")
        self.ax.set_ylabel("GPA")
        self.ax.set_ylim(0, 4)

        if not terms:
            self.canvas.draw()
            return

        x_labels = [t[0] for t in terms]
        y_vals = [t[1] for t in terms]

        self.ax.plot(range(len(x_labels)), y_vals, marker="o")
        self.ax.set_xticks(range(len(x_labels)))
        self.ax.set_xticklabels(x_labels, rotation=30, ha="right")

        # Simple performance annotation
        avg = sum(y_vals) / len(y_vals)
        self.ax.axhline(avg, linestyle="--")
        self.ax.text(0.02, 0.95, f"Avg: {avg:.2f}", transform=self.ax.transAxes, va="top")

        self.canvas.draw()


if __name__ == "__main__":
    app = StudentSystemApp()
    app.mainloop()
