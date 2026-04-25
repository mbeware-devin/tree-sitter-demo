/**
 * sample.c - A sample C file to demonstrate tree-sitter parsing.
 *
 * This file contains a variety of C constructs:
 *   - Preprocessor directives (#include, #define)
 *   - Struct and enum definitions
 *   - Typedefs
 *   - Function prototypes and definitions
 *   - Global and local variables
 *   - Function calls and control flow
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_NAME_LEN 64
#define BUFFER_SIZE  1024
#define SQUARE(x)    ((x) * (x))

/* ---------- Enum ---------- */
typedef enum {
    STATUS_OK = 0,
    STATUS_ERROR,
    STATUS_TIMEOUT,
} Status;

/* ---------- Struct ---------- */
typedef struct {
    int  id;
    char name[MAX_NAME_LEN];
    int  score;
} Student;

/* ---------- Function prototypes ---------- */
Student *create_student(int id, const char *name, int score);
void     print_student(const Student *s);
void     free_student(Student *s);
Status   update_score(Student *s, int new_score);

/* ---------- Global variable ---------- */
static int student_count = 0;

/* ---------- Helper: validate score ---------- */
static Status validate_score(int score) {
    if (score < 0 || score > 100) {
        fprintf(stderr, "Invalid score: %d\n", score);
        return STATUS_ERROR;
    }
    return STATUS_OK;
}

/* ---------- create_student ---------- */
Student *create_student(int id, const char *name, int score) {
    if (validate_score(score) != STATUS_OK) {
        return NULL;
    }

    Student *s = (Student *)malloc(sizeof(Student));
    if (s == NULL) {
        perror("malloc");
        return NULL;
    }

    s->id    = id;
    s->score = score;
    strncpy(s->name, name, MAX_NAME_LEN - 1);
    s->name[MAX_NAME_LEN - 1] = '\0';

    student_count++;
    return s;
}

/* ---------- print_student ---------- */
void print_student(const Student *s) {
    if (s == NULL) {
        printf("(null student)\n");
        return;
    }
    printf("Student #%d: %s, score=%d (score^2=%d)\n",
           s->id, s->name, s->score, SQUARE(s->score));
}

/* ---------- free_student ---------- */
void free_student(Student *s) {
    if (s != NULL) {
        student_count--;
        free(s);
    }
}

/* ---------- update_score ---------- */
Status update_score(Student *s, int new_score) {
    if (s == NULL) {
        return STATUS_ERROR;
    }
    Status rc = validate_score(new_score);
    if (rc != STATUS_OK) {
        return rc;
    }
    s->score = new_score;
    return STATUS_OK;
}

/* ---------- main ---------- */
int main(int argc, char *argv[]) {
    char buffer[BUFFER_SIZE];

    printf("=== Tree-sitter C demo ===\n");

    Student *alice = create_student(1, "Alice", 95);
    Student *bob   = create_student(2, "Bob", 82);

    print_student(alice);
    print_student(bob);

    Status result = update_score(alice, 99);
    if (result == STATUS_OK) {
        printf("Updated Alice's score:\n");
        print_student(alice);
    }

    /* Demonstrate error path */
    result = update_score(bob, -5);
    if (result != STATUS_OK) {
        fprintf(stderr, "Failed to update Bob's score.\n");
    }

    printf("Total students created: %d\n", student_count);

    snprintf(buffer, BUFFER_SIZE, "Summary: %s=%d, %s=%d",
             alice->name, alice->score,
             bob->name, bob->score);
    printf("%s\n", buffer);

    free_student(alice);
    free_student(bob);

    printf("Total students after cleanup: %d\n", student_count);
    return EXIT_SUCCESS;
}
