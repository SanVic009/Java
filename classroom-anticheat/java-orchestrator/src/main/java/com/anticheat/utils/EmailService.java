package com.anticheat.utils;

import jakarta.mail.*;
import jakarta.mail.internet.*;
import java.io.File;
import java.util.Properties;

public class EmailService {

    private static final String SMTP_HOST = "smtp.gmail.com";
    private static final String SMTP_PORT = "587";
    private final String username;
    private final String password;
    private final Session session;

    public EmailService() {
        this.username = System.getenv("SMTP_USER");
        this.password = System.getenv("SMTP_PASS");

        if (this.username == null || this.username.isEmpty() || this.password == null || this.password.isEmpty()) {
            System.err.println("WARNING: SMTP_USER or SMTP_PASS environment variables are not set. EmailService will not be able to authenticate.");
        }

        Properties props = new Properties();
        props.put("mail.smtp.auth", "true");
        props.put("mail.smtp.starttls.enable", "true");
        props.put("mail.smtp.host", SMTP_HOST);
        props.put("mail.smtp.port", SMTP_PORT);

        this.session = Session.getInstance(props, new Authenticator() {
            @Override
            protected PasswordAuthentication getPasswordAuthentication() {
                return new PasswordAuthentication(username, password);
            }
        });
    }

    /**
     * Sends a plain text email.
     *
     * @param recipient the recipient's email address
     * @param subject   the subject of the email
     * @param body      the body of the email
     * @throws MessagingException if there is a failure while sending the email
     */
    public void sendTextEmail(String recipient, String subject, String body) throws MessagingException {
        Message message = new MimeMessage(session);
        message.setFrom(new InternetAddress(username));
        message.setRecipients(Message.RecipientType.TO, InternetAddress.parse(recipient));
        message.setSubject(subject);
        message.setText(body);

        Transport.send(message);
    }

    /**
     * Sends an email with a file attachment. If the file does not exist, sends a plain text email.
     *
     * @param recipient the recipient's email address
     * @param subject   the subject of the email
     * @param body      the body of the email (plain text)
     * @param filePath  the absolute or relative path to the attachment file
     * @throws MessagingException if there is a failure while sending the email
     */
    public void sendEmailWithAttachment(String recipient, String subject, String body, String filePath) throws MessagingException {
        File attachmentContext = new File(filePath);
        if (!attachmentContext.exists() || !attachmentContext.isFile()) {
            System.err.println("WARNING: Attachment file does not exist at path: " + filePath + ". Falling back to plain text email.");
            sendTextEmail(recipient, subject, body);
            return;
        }

        Message message = new MimeMessage(session);
        message.setFrom(new InternetAddress(username));
        message.setRecipients(Message.RecipientType.TO, InternetAddress.parse(recipient));
        message.setSubject(subject);

        // Create the message part (the text body)
        BodyPart messageBodyPart = new MimeBodyPart();
        messageBodyPart.setText(body);

        // Create a multipart message
        Multipart multipart = new MimeMultipart();
        
        // Set text message part
        multipart.addBodyPart(messageBodyPart);

        // Second part is attachment
        MimeBodyPart attachmentPart = new MimeBodyPart();
        try {
            attachmentPart.attachFile(attachmentContext);
        } catch (Exception e) {
            System.err.println("WARNING: Failed to attach file: " + filePath + ". Falling back to plain text email. Error: " + e.getMessage());
            sendTextEmail(recipient, subject, body);
            return;
        }
        multipart.addBodyPart(attachmentPart);

        // Send the complete message parts
        message.setContent(multipart);

        Transport.send(message);
    }
}
