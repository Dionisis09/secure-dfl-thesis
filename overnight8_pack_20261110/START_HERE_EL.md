# Νυχτερινή σειρά έως 8 ώρες — CIFAR-10, 60 γύροι

Σκοπός: έλεγχος σύγκλισης CNN/MLP και διατήρησης της accuracy με adaptive,
με προαιρετικό έλεγχο πιο έντονης ετερογένειας.

- Υποχρεωτικά 24 runs: IID / Dirichlet α=0,5, CNN/MLP, baseline/adaptive,
  seeds 1/2/3, 20 clients, ring, πλήρες dataset.
- Προαιρετικά 12 runs με α=0,1, μόνο αν χωράνε με πραγματικό calibration.
- 60 γύροι και cosine schedule 60 γύρων, από την αρχή με κοινά seeds.
- Νέο κοινό οκτάωρο από το πρώτο calibration, με 1 ώρα περιθώριο μέσα στο όριο.
- Το `selected_plan.json` δείχνει αν επιλέχθηκαν 24 ή 36 runs.
- Το `state.json` δείχνει την ακριβή ώρα λήξης. Παύσεις/sleep δεν παρατείνουν το όριο.

Η ρητή εντολή `start` εκτελεί calibration → επιλογή → νέα πειράματα.
Το άνοιγμα του φακέλου δεν εκτελεί πειράματα. Από τον γονικό φάκελο:

```powershell
.\scripts\start_overnight8.ps1 status
.\scripts\start_overnight8.ps1 pause
# Αργότερα, μέσα στο ίδιο οκτάωρο:
.\scripts\start_overnight8.ps1 clear-pause
.\scripts\start_overnight8.ps1 start
.\scripts\start_overnight8.ps1 summarize
```

Η σύγκριση με τα παλιά 20-round αποτελέσματα αλλάζει horizon και scheduler.
Οι validation μετρήσεις 20/40/60 μέσα στη νέα ίδια τροχιά δείχνουν τη σύγκλιση.
Test scores και sample SD υπολογίζονται από πλήρεις ομάδες τριών seeds.
Δεν εγγυάται συγκεκριμένη accuracy. Ο trainer βλέπει plaintext μοντέλα/κλειδιά,
όπως στην εγκεκριμένη trusted-simulator υλοποίηση.

Αναλυτικά: `docs/OVERNIGHT8_EL.md` στη ρίζα του project.
