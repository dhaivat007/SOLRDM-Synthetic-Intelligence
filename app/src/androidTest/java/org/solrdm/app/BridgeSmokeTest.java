package org.solrdm.app;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.test.InstrumentationTestCase;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import java.io.File;

/** Run the two phases separately with scripts/smoke-test.sh, which kills the process. */
public class BridgeSmokeTest extends InstrumentationTestCase {
    private Activity activity;

    private void launch() {
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity = getInstrumentation().startActivitySync(intent);
        getInstrumentation().waitForIdleSync();
    }

    private String observe(final String sentence) throws Throwable {
        final String[] response = new String[1];
        runTestOnUiThread(() -> {
            EditText input = activity.findViewById(R.id.observation_input);
            Button button = activity.findViewById(R.id.observe_button);
            TextView output = activity.findViewById(R.id.observation_output);
            assertNotNull(input);
            assertNotNull(button);
            assertNotNull(output);
            input.setText(sentence);
            assertTrue("Observe click was not handled", button.performClick());
            response[0] = output.getText().toString();
        });
        return response[0];
    }

    private File databaseFile() {
        return new File(getInstrumentation().getTargetContext().getFilesDir(), "solrdm.sqlite3");
    }

    private void assertRows(int expected) {
        assertTrue("Python SQLite database is missing", databaseFile().isFile());
        SQLiteDatabase db = SQLiteDatabase.openDatabase(
                databaseFile().getAbsolutePath(), null, SQLiteDatabase.OPEN_READONLY);
        try {
            Cursor count = db.rawQuery("SELECT COUNT(*) FROM observations", null);
            try {
                assertTrue(count.moveToFirst());
                assertEquals(expected, count.getInt(0));
            } finally {
                count.close();
            }
            Cursor fact = db.rawQuery(
                    "SELECT subject, predicate, object FROM observations ORDER BY rowid LIMIT 1", null);
            try {
                assertTrue(fact.moveToFirst());
                assertEquals("rotor", fact.getString(0));
                assertEquals("part_of", fact.getString(1));
                assertEquals("motor", fact.getString(2));
            } finally {
                fact.close();
            }
        } finally {
            db.close();
        }
    }

    public void testFirstLaunchWritesObservation() throws Throwable {
        assertFalse("Start the write phase with cleared app data", databaseFile().exists());
        launch();
        assertEquals("Stored: rotor → part_of → motor. Observations: 1",
                observe("Rotor is part of a motor"));
        assertRows(1);
        assertEquals("Unsupported sentence structure; no fact saved.", observe("Unsupported input"));
        assertRows(1);
    }

    public void testRestartPreservesObservation() throws Throwable {
        // Check persistence before loading the Python runtime in the new process.
        assertRows(1);
        launch();
        assertEquals("Stored: wheel → part_of → car. Observations: 2",
                observe("Wheel is part of a car"));
        assertRows(2);
    }

    @Override protected void tearDown() throws Exception {
        try {
            if (activity != null) {
                getInstrumentation().runOnMainSync(() -> activity.finish());
                getInstrumentation().waitForIdleSync();
            }
        } finally {
            super.tearDown();
        }
    }
}
