"""Shared curriculum settings. Reuse these in future tools (quiz, assignment, etc.)
so every tool asks for the same Curriculum / Subject / Class choices."""

CURRICULA = {
    "cbc": {
        "label": "CBC (Forms)",
        "class_label": "Class (Form)",
        "classes": ["Form 1", "Form 2", "Form 3", "Form 4"],
    },
    "old": {
        "label": "Old curriculum (Grades)",
        "class_label": "Grade",
        "classes": ["Grade 8", "Grade 9", "Grade 10", "Grade 11", "Grade 12"],
    },
}

SUBJECTS = [
    "Physics",
    "Chemistry",
    "Biology",
    "Agricultural Science",
    "Creative Arts",
    "English Language",
    "English",
    "Civic Education",
    "Home Economics",
    "Mathematics",
    "Additional Mathematics",
    "Computer Studies",
    "Computer Studies / ICT",
    "ICT",
    "Design and Technology",
    "Geography",
    "Business Studies",
]

DURATIONS = [40, 60, 80, 120]  # minutes; 40 is the default shown in the form

TOPICS = {
    "Physics": [
        "Forces and Motion",
        "Electricity",
        "Heat and Temperature",
    ],
    "Chemistry": [
        "Periodic Table",
        "Acids and Bases",
        "Chemical Bonding",
    ],
    "Biology": [
        "Cell Structure",
        "Photosynthesis",
        "Human Body Systems",
    ],
    "Agricultural Science": [
        "Crop Production",
        "Soil and Water Management",
        "Animal Husbandry",
    ],
    "Creative Arts": [
        "Colour Theory",
        "Drawing and Design",
        "Art Appreciation",
    ],
    "English Language": [
        "Comprehension",
        "Grammar and Tenses",
        "Creative Writing",
    ],
    "English": [
        "Comprehension",
        "Grammar and Tenses",
        "Creative Writing",
    ],
    "Civic Education": [
        "Citizenship",
        "Local Government",
        "Leadership and Governance",
    ],
    "Home Economics": [
        "Nutrition and Health",
        "Food Preparation",
        "Home Management",
    ],
    "Mathematics": [
        "Fractions",
        "Ratio and Proportion",
        "Triangles",
    ],
    "Additional Mathematics": [
        "Quadratic Equations",
        "Sequences",
        "Trigonometry",
    ],
    "Computer Studies": [
        "Algorithms Basics",
        "Programming Intro",
        "Internet and Safety",
    ],
    "Computer Studies / ICT": [
        "Computer Basics",
        "File Management",
        "Spreadsheets",
    ],
    "ICT": [
        "Computer Basics",
        "File Management",
        "Spreadsheets",
    ],
    "Design and Technology": [
        "Introduction to Tools",
        "Triangles and Roofs",
        "Materials and Safety",
    ],
    "Geography": [
        "Map Reading",
        "Weather and Climate",
        "Population and Settlement",
    ],
    "Business Studies": [
        "Marketing",
        "Business Planning",
        "Entrepreneurship",
    ],
}
